"""History can check an attachment without transferring its media payload."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web


def test_media_head_checks_existing_missing_and_unsafe_files(monkeypatch, tmp_path):
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    folder = tmp_path / '_inbox' / 'scope'
    folder.mkdir(parents=True)
    (folder / 'video.mp4').write_bytes(b'video payload')
    client = TestClient(web.app, base_url='http://localhost')
    response = client.head('/api/media/_inbox/scope/video.mp4')
    assert response.status_code == 200
    assert response.content == b''
    assert int(response.headers['content-length']) == len(b'video payload')
    assert client.get('/api/media/_inbox/scope/video.mp4').content == b'video payload'
    assert client.head('/api/media/_inbox/missing.mp4').status_code == 404
    assert client.head('/api/media/%2e%2e/secret.txt').status_code == 403
