"""PWA endpoints expose only the app shell and revalidate deployment metadata."""
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web


@pytest.mark.parametrize('name,media', [('sw.js', 'application/javascript'),
                                      ('manifest.webmanifest', 'application/manifest+json'),
                                      ('app-icon.png', 'image/png')])
def test_shell_resources_revalidate_and_support_proxy_root(monkeypatch, tmp_path, name, media):
    monkeypatch.setattr(web, 'REACT_DIR', tmp_path)
    (tmp_path / name).write_bytes(b'test shell resource')
    with TestClient(web.app, base_url='http://localhost', root_path='/easel') as client:
        response = client.get('/' + name)
    assert response.status_code == 200
    assert response.content == b'test shell resource'
    assert response.headers['content-type'].startswith(media)
    assert response.headers['cache-control'] == 'no-cache'


def test_shell_resources_do_not_fall_back_to_html(monkeypatch, tmp_path):
    monkeypatch.setattr(web, 'REACT_DIR', tmp_path)
    (tmp_path / 'index.html').write_text('<html>app</html>')
    with TestClient(web.app, base_url='http://localhost') as client:
        assert client.get('/sw.js').status_code == 404
        assert client.get('/private-config.json').status_code == 404
