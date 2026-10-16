"""Exercise the real launcher without starting a server or invoking shell from .env."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_launcher(tmp_path, settings, public_url=None):
    shutil.copy2(ROOT / 'start-web-lan.sh', tmp_path / 'start-web-lan.sh')
    (tmp_path / '.env').write_text(settings)
    bin_dir = tmp_path / '.venv/bin'
    bin_dir.mkdir(parents=True)
    (bin_dir / 'python').write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    (bin_dir / 'python').chmod(0o755)
    (bin_dir / 'easel').write_text('#!' + sys.executable + '\nimport json,os,sys\nprint(json.dumps({"hosts":os.environ.get("EASEL_EXTRA_HOSTS"),"origins":os.environ.get("EASEL_EXTRA_ORIGINS"),"args":sys.argv[1:]}))\n')
    (bin_dir / 'easel').chmod(0o755)
    (bin_dir / 'ipconfig').write_text('#!/bin/sh\nprintf "192.168.31.200\\n"\n')
    (bin_dir / 'ipconfig').chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
           'PYTHONPATH': str(ROOT), 'EASEL_EXTRA_HOSTS': 'existing.test',
           'EASEL_EXTRA_ORIGINS': 'https://existing.test'}
    env.pop('EASEL_PUBLIC_URL', None)
    if public_url is not None:
        env['EASEL_PUBLIC_URL'] = public_url
    return subprocess.run(['bash', str(tmp_path / 'start-web-lan.sh'), '--port', '7860'],
                          cwd='/', env=env, capture_output=True, text=True)


def test_launcher_combines_lan_and_configured_origin_without_sourcing_env(tmp_path):
    marker = tmp_path / 'must-not-exist'
    result = run_launcher(tmp_path, f'EASEL_PUBLIC_URL="https://chat.example:8443/"\nUNRELATED=$(touch {marker})\n')
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.splitlines()[-1])
    assert data['hosts'] == 'existing.test,192.168.31.200,chat.example'
    assert data['origins'] == 'https://existing.test,http://192.168.31.200:7860,https://chat.example:8443'
    assert data['args'] == ['web', '--port', '7860']
    assert not marker.exists()


def test_launcher_environment_can_disable_public_origin(tmp_path):
    result = run_launcher(tmp_path, 'EASEL_PUBLIC_URL=https://chat.example\n', public_url='')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])['hosts'] == 'existing.test,192.168.31.200'


def test_launcher_rejects_invalid_public_url_without_echoing_credentials(tmp_path):
    result = run_launcher(tmp_path, 'EASEL_PUBLIC_URL=https://user:secret@chat.example/path\n')
    assert result.returncode != 0
    assert 'EASEL_PUBLIC_URL' in result.stderr
    assert 'secret' not in result.stderr + result.stdout
