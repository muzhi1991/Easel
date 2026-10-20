"""Exercise the real launcher with a Web process and a disappearing old gateway."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def isolated_gateway_script(tmp_path):
    # Run the production shell code with only its log destination relocated.
    # Never truncate the running instance's /tmp/easel-gateway.log in tests.
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    script = scripts / 'gateway.sh'
    source = (ROOT / 'scripts/gateway.sh').read_text()
    script.write_text(source.replace('LOGFILE="/tmp/easel-gateway.log"',
                                     f'LOGFILE="{tmp_path}/gateway.log"'))
    return script


def test_launcher_recovers_gateway_that_exits_after_startup(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / '.venv/bin').mkdir(parents=True)
    (tmp_path / 'scripts/gateway.sh').write_text(
        'echo start >> starts\ntouch healthy\n', encoding='utf-8')
    web = tmp_path / '.venv/bin/easel'
    web.write_text(f'#!{sys.executable}\n' + textwrap.dedent('''\
        import pathlib, time, sys
        root = pathlib.Path.cwd()
        # The startup probe saw the old gateway, which now finishes shutting down.
        (root / 'healthy').unlink()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if (root / 'healthy').exists():
                sys.exit(0)
            time.sleep(.01)
        sys.exit(9)
        '''), encoding='utf-8')
    web.chmod(0o755)
    harness = textwrap.dedent('''\
        from pathlib import Path
        from unittest.mock import patch
        from easel import web_startup as launcher
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        def health(*args, **kwargs):
            if not Path('healthy').exists(): raise ConnectionRefusedError()
            return Response()
        with patch.object(launcher, 'read_settings', return_value={}), \\
             patch.object(launcher, 'settings', return_value={'runtime': 'openclaw'}), \\
             patch.object(launcher.urllib.request, 'urlopen', side_effect=health):
            launcher.GATEWAY_CHECK_INTERVAL = .02
            launcher.main()
        ''')
    env = {**os.environ, 'PYTHONPATH': str(ROOT)}
    result = subprocess.run([sys.executable, '-c', harness], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'starts').read_text().splitlines() == ['start', 'start']


def test_recovery_start_does_not_force_an_occupied_port(tmp_path):
    tools = tmp_path / 'bin'
    tools.mkdir()
    for name, content in {
        'curl': 'exit 22',
        'lsof': 'echo 99999',
        'ss': 'echo "127.0.0.1:19199 users:(pid=99999)"',
        'openclaw': 'touch "$CALLED_MARKER"',
    }.items():
        command = tools / name
        command.write_text('#!/bin/sh\n' + content + '\n')
        command.chmod(0o755)
    marker = tmp_path / 'openclaw-called'
    env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
           'EASEL_GATEWAY_PORT': '19199', 'OPENCLAW_GATEWAY_PORT': '19199',
           'CALLED_MARKER': str(marker), 'PYTHONPATH': str(ROOT)}
    result = subprocess.run(['bash', str(isolated_gateway_script(tmp_path)), 'start', '--no-force'],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert '不强制接管' in result.stderr
    assert not marker.exists()


def test_recovery_can_start_without_force_under_system_bash(tmp_path):
    tools = tmp_path / 'bin'
    tools.mkdir()
    marker = tmp_path / 'openclaw-args'
    for name, content in {
        'curl': 'test -f "$CALLED_MARKER"',
        'lsof': 'exit 0',
        'ss': 'exit 0',
        'openclaw': 'printf "%s\\n" "$@" > "$CALLED_MARKER"',
    }.items():
        command = tools / name
        command.write_text('#!/bin/sh\n' + content + '\n')
        command.chmod(0o755)
    env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
           'EASEL_GATEWAY_PORT': '19199', 'OPENCLAW_GATEWAY_PORT': '19199',
           'EASEL_RAW_STREAM_PATH': str(tmp_path / 'raw.jsonl'),
           'CALLED_MARKER': str(marker), 'PYTHONPATH': str(ROOT)}
    result = subprocess.run(['/bin/bash', str(isolated_gateway_script(tmp_path)), 'start', '--no-force'],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text().splitlines() == [
        '--profile', 'easel', 'gateway', 'run', '--allow-unconfigured', '--bind', 'loopback']
    assert 'Gateway started' in result.stdout
