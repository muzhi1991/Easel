"""Package committed source plus a prebuilt frontend; never deploy or read local config."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def build(root: Path, output: Path) -> Path:
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dist = root / 'web/frontend/dist'
    for required in ['index.html', 'sw.js', 'manifest.webmanifest', 'app-icon.png']:
        if not (dist / required).is_file():
            raise ValueError(f'Missing frontend build: {required}')
    assets = sorted(p for p in dist.rglob('*') if p.is_file())
    if any(p.is_symlink() for p in dist.rglob('*')):
        raise ValueError('Frontend build must not contain symlinks')
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'easel-dev-{commit[:12]}.tar.gz'
    source = subprocess.check_output(['git', 'archive', '--format=tar', '--prefix=easel/', 'HEAD'], cwd=root)
    metadata = {
        'commit': commit,
        'format': 1,
        'contents': 'Committed source and browser assets; install Python dependencies on the target OS.',
        'frontend_sha256': {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest() for p in assets},
    }
    with tarfile.open(fileobj=io.BytesIO(source)) as tracked, tarfile.open(target, 'w:gz') as bundle:
        for member in tracked:
            bundle.addfile(member, tracked.extractfile(member) if member.isfile() else None)
        for path in assets:
            bundle.add(path, arcname='easel/web/frontend/dist/' + path.relative_to(dist).as_posix())
        manifest = json.dumps(metadata, indent=2).encode() + b'\n'
        info = tarfile.TarInfo('easel/BUILD-INFO.json')
        info.size = len(manifest)
        info.mode = 0o644
        bundle.addfile(info, io.BytesIO(manifest))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / 'SHA256SUMS').write_text(f'{digest}  {target.name}\n')
    print(f'Built {target.name} from {commit}; no deployment performed.')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output_dir)
