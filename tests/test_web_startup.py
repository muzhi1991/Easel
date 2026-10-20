from unittest.mock import Mock

import pytest

from easel import web_startup


def test_openclaw_starts_before_readiness_check(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(web_startup, 'read_settings', lambda _: {})
    monkeypatch.setattr(web_startup, 'settings', lambda *_: {'runtime': 'openclaw'})
    def run(args, **kwargs):
        calls.append('start')
        assert args == ['bash', str(tmp_path / 'scripts/gateway.sh'), 'start']
        assert kwargs['check'] is True
        assert kwargs['env'] == {'PATH': '/test/bin'}
    monkeypatch.setattr(web_startup.subprocess, 'run', run)
    def health(*args, **kwargs):
        calls.append('health')
        assert calls == ['start', 'health']
        raise ConnectionRefusedError()
    monkeypatch.setattr(web_startup.urllib.request, 'urlopen', health)
    with pytest.raises(ConnectionRefusedError):
        web_startup.ensure_gateway(tmp_path, {'PATH': '/test/bin'})


def test_other_runtimes_do_not_start_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(web_startup, 'read_settings', lambda _: {})
    monkeypatch.setattr(web_startup, 'settings', lambda *_: {'runtime': 'api'})
    run = Mock()
    monkeypatch.setattr(web_startup.subprocess, 'run', run)
    web_startup.ensure_gateway(tmp_path, {})
    run.assert_not_called()


def test_failed_gateway_prevents_web_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web_startup, 'web_environment', lambda env: {'PATH': '/bin'})
    def fail(*_):
        raise ConnectionRefusedError()
    monkeypatch.setattr(web_startup, 'ensure_gateway', fail)
    execute = Mock()
    monkeypatch.setattr(web_startup.os, 'execve', execute)
    with pytest.raises(SystemExit) as error:
        web_startup.main()
    assert error.value.code == 1
    execute.assert_not_called()


def test_ready_gateway_allows_supervised_web_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web_startup, 'web_environment', lambda env: {'PATH': '/bin'})
    ready = Mock(return_value=True)
    monkeypatch.setattr(web_startup, 'ensure_gateway', ready)
    supervise = Mock(return_value=7)
    monkeypatch.setattr(web_startup, 'supervise_web', supervise)
    monkeypatch.setattr(web_startup.sys, 'argv', ['web_startup', '--port', '7860'])
    with pytest.raises(SystemExit) as error:
        web_startup.main()
    assert error.value.code == 7
    ready.assert_called_once()
    assert supervise.call_args.args[2] == [str(tmp_path / '.venv/bin/easel'), 'web', '--port', '7860']


def test_other_runtime_keeps_direct_web_execution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web_startup, 'web_environment', lambda env: {'PATH': '/bin'})
    monkeypatch.setattr(web_startup, 'ensure_gateway', Mock(return_value=False))
    supervise = Mock()
    monkeypatch.setattr(web_startup, 'supervise_web', supervise)
    execute = Mock()
    monkeypatch.setattr(web_startup.os, 'execve', execute)
    monkeypatch.setattr(web_startup.sys, 'argv', ['web_startup'])
    web_startup.main()
    supervise.assert_not_called()
    assert execute.call_args.args[1] == ['easel', 'web']


def test_recovery_failure_is_retried_without_replaying_web(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(web_startup, '_uses_gateway', lambda _: True)
    web = Mock(pid=98765)
    # Two monitor ticks (first recovery fails), then the original Web exits.
    web.wait.side_effect = [subprocess.TimeoutExpired('web', 5),
                            subprocess.TimeoutExpired('web', 5), 0]
    web.poll.return_value = 0
    spawn = Mock(return_value=web)
    monkeypatch.setattr(web_startup.subprocess, 'Popen', spawn)
    monkeypatch.setattr(web_startup, '_check_gateway', Mock(side_effect=ConnectionRefusedError))
    recover = Mock(side_effect=[subprocess.CalledProcessError(1, 'gateway'), True])
    monkeypatch.setattr(web_startup, 'ensure_gateway', recover)
    assert web_startup.supervise_web(tmp_path, {}, ['easel', 'web']) == 0
    assert recover.call_count == 2
    assert all(call.kwargs == {'recovery': True} for call in recover.call_args_list)
    spawn.assert_called_once()


def test_shutdown_forwards_to_web_group_without_gateway_recovery(tmp_path, monkeypatch):
    import signal
    import subprocess
    handlers = {}
    def register(sig, handler):
        old = handlers.get(sig)
        handlers[sig] = handler
        return old
    monkeypatch.setattr(web_startup.signal, 'signal', register)
    web = Mock(pid=98765)
    web.poll.return_value = None
    def first_tick(*args, **kwargs):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        web.poll.return_value = 0
        raise subprocess.TimeoutExpired('web', 5)
    waits = iter([True, False])
    def wait(**kwargs):
        if next(waits):
            return first_tick()
        return 0
    web.wait.side_effect = wait
    monkeypatch.setattr(web_startup.subprocess, 'Popen', Mock(return_value=web))
    kill = Mock()
    monkeypatch.setattr(web_startup.os, 'killpg', kill)
    recover = Mock()
    monkeypatch.setattr(web_startup, 'ensure_gateway', recover)
    assert web_startup.supervise_web(tmp_path, {}, ['easel', 'web']) == 0
    kill.assert_called_once_with(web.pid, signal.SIGTERM)
    recover.assert_not_called()
    assert handlers == {signal.SIGTERM: None, signal.SIGINT: None}
