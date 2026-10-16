import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile


def test_bundle_uses_commit_not_local_secrets(tmp_path):
    spec = importlib.util.spec_from_file_location('bundle', Path(__file__).parents[1] / 'scripts/build_deployment_bundle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init')
    (tmp_path / 'app.py').write_text('committed source')
    (tmp_path / '.env.example').write_text('API_KEY=')
    git('add', 'app.py', '.env.example')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
    (tmp_path / 'app.py').write_text('dirty source')
    (tmp_path / '.env').write_text('PRIVATE_KEY=must-not-package')
    (tmp_path / 'user-config.json').write_text('must-not-package')
    dist = tmp_path / 'web/frontend/dist'
    dist.mkdir(parents=True)
    for name in ['index.html', 'sw.js', 'manifest.webmanifest', 'app-icon.png']:
        (dist / name).write_text('built asset')
    output = tmp_path / 'release'
    bundle = module.build(tmp_path, output)
    with tarfile.open(bundle) as archive:
        assert archive.extractfile('easel/app.py').read() == b'committed source'
        assert 'easel/.env' not in archive.getnames()
        assert 'easel/user-config.json' not in archive.getnames()
        assert archive.extractfile('easel/web/frontend/dist/index.html').read() == b'built asset'
        info = json.load(archive.extractfile('easel/BUILD-INFO.json'))
        assert info['commit'] == git('rev-parse', 'HEAD')
        assert info['frontend_sha256']['index.html'] == hashlib.sha256(b'built asset').hexdigest()
    assert (output / 'SHA256SUMS').read_text().split()[0] == hashlib.sha256(bundle.read_bytes()).hexdigest()
