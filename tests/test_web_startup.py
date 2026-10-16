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


def test_ready_gateway_allows_web_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web_startup, 'web_environment', lambda env: {'PATH': '/bin'})
    ready = Mock()
    monkeypatch.setattr(web_startup, 'ensure_gateway', ready)
    execute = Mock()
    monkeypatch.setattr(web_startup.os, 'execve', execute)
    monkeypatch.setattr(web_startup.sys, 'argv', ['web_startup', '--port', '7860'])
    web_startup.main()
    ready.assert_called_once()
    assert execute.call_args.args[0] == str(tmp_path / '.venv/bin/easel')
    assert execute.call_args.args[1] == ['easel', 'web', '--port', '7860']
