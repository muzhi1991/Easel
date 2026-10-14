import base64
import importlib.util
import io
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/media-adapters/src'))
from easel_media_adapters import ImageRequest, MediaError, MediaRuntime
from easel_media_adapters import image


def instance(rt, name='flare', edit=False):
    return rt.save_provider({'id': name, 'name': name, 'adapter': 'openai-image', 'settings': {
        'base_url': 'https://image.test/v1', 'model': name, 'supports_edit': edit,
    }}, ['image'] if name == 'flare' else [])


def encoded():
    b = io.BytesIO()
    Image.new('RGB', (16, 16), 'red').save(b, 'PNG')
    return base64.b64encode(b.getvalue()).decode()


def mock(monkeypatch, handler):
    monkeypatch.setattr(image, 'client', lambda settings: httpx.Client(transport=httpx.MockTransport(handler)))


def test_multiple_images_and_explicit_choice(tmp_path, monkeypatch):
    rt = MediaRuntime(tmp_path / 'config.json')
    instance(rt); instance(rt, 'sunburst')
    seen = []
    def handle(req):
        import json
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={'data': [{'b64_json': encoded()}] * 2})
    mock(monkeypatch, handle)
    result = rt.submit('image', 'generate_image', ImageRequest('draw', tmp_path / 'out.png', n=2), 'sunburst')
    assert seen[0]['model'] == 'sunburst'
    assert rt.load()['defaults']['image'] == 'flare'
    assert len(result['outputs']) == 2
    for p in result['outputs']:
        with Image.open(p) as im: assert im.size == (16, 16)


@pytest.mark.parametrize('status,error,quota', [
    (429, {'code': 'insufficient_quota'}, True),
    (402, {'code': 'insufficient_balance'}, True),
    (429, {'code': 'rate_limit_exceeded'}, False),
    (500, {'message': 'secret insufficient quota'}, False),
])
def test_only_explicit_quota_no_retry(tmp_path, monkeypatch, status, error, quota):
    rt = MediaRuntime(tmp_path / 'config.json'); instance(rt)
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(status, json={'error': error})
    mock(monkeypatch, handle)
    with pytest.raises(MediaError) as exc:
        rt.submit('image', 'generate_image', ImageRequest('draw', tmp_path / 'out.png'))
    assert ('IMAGE_QUOTA_EXHAUSTED' in str(exc.value)) is quota
    assert 'secret' not in str(exc.value)
    assert len(calls) == 1
    assert not (tmp_path / 'out.png').exists()


def test_edit_capability_and_multipart(tmp_path, monkeypatch):
    rt = MediaRuntime(tmp_path / 'config.json'); instance(rt)
    source = tmp_path / 'input.png'; source.write_bytes(base64.b64decode(encoded()))
    request = ImageRequest('edit', tmp_path / 'out.webp', image=source, format='webp')
    with pytest.raises(MediaError, match='未声明'):
        rt.submit('image', 'generate_image', request)
    instance(rt, edit=True)
    def handle(req):
        assert req.url.path == '/v1/images/edits'
        assert 'multipart/form-data' in req.headers['content-type']
        assert b'name="image"' in req.content
        return httpx.Response(200, json={'data': [{'b64_json': encoded()}]})
    mock(monkeypatch, handle)
    rt.submit('image', 'generate_image', request)
    with Image.open(tmp_path / 'out.webp') as im: assert im.format == 'WEBP'


def test_invalid_image_preserves_existing_file(tmp_path, monkeypatch):
    rt = MediaRuntime(tmp_path / 'config.json'); instance(rt)
    out = tmp_path / 'out.png'; out.write_bytes(b'old')
    mock(monkeypatch, lambda r: httpx.Response(200, json={'data': [{'b64_json': 'bm90IGFuIGltYWdl'}]}))
    with pytest.raises(MediaError, match='有效图片'):
        rt.submit('image', 'generate_image', ImageRequest('draw', out))
    assert out.read_bytes() == b'old'


def test_cli_uses_default_and_keeps_legacy_opt_in(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / 'skills/shared/scripts'))
    spec = importlib.util.spec_from_file_location('image_cli_test', ROOT / 'skills/shared/scripts/ai_image.py')
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    monkeypatch.setenv('EASEL_MEDIA_CONFIG', str(tmp_path / 'config.json'))
    rt = MediaRuntime(); instance(rt); instance(rt, 'qwen')
    assert cli.run_media_instance(cli.parse_args(['check']))
    assert 'flare' in capsys.readouterr().out
    assert cli.run_media_instance(cli.parse_args(['check', '--provider', 'qwen']))
    assert 'qwen' in capsys.readouterr().out
    assert not cli.run_media_instance(cli.parse_args(['check', '--provider', 'legacy']))
    calls = []
    mock(monkeypatch, lambda r: calls.append(r) or httpx.Response(200, json={'data': [{'b64_json': encoded()}]}))
    args = cli.parse_args(['text2img', '--prompt', 'draw', '-o', str(tmp_path / 'out.png')])
    assert cli.run_media_instance(args)
    assert len(calls) == 1
    assert (tmp_path / 'out.png').is_file()


def test_curl_json_keeps_payload_and_secret_off_argv(tmp_path, monkeypatch):
    import json
    from easel_media_adapters import http
    monkeypatch.setenv('EASEL_MEDIA_TEST_KEY', 'secret-for-test')
    def run(argv, **kw):
        assert 'secret-for-test' not in ' '.join(argv)
        lines = kw['input'].splitlines()
        assert 'header = "Authorization: Bearer secret-for-test"' in lines
        path = json.loads(next(l.split(' = ', 1)[1] for l in lines if l.startswith('data-binary')))[1:]
        assert json.loads(Path(path).read_text()) == {'model': 'flare', 'prompt': '你好'}
        out = json.loads(next(l.split(' = ', 1)[1] for l in lines if l.startswith('output =')))
        Path(out).write_text('{"data": []}')
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout='200')
    monkeypatch.setattr(http.subprocess, 'run', run)
    with http.client({'transport': 'curl', 'api_key_env': 'EASEL_MEDIA_TEST_KEY'}) as c:
        assert c.post('https://image.test/v1/images/generations', json={'model': 'flare', 'prompt': '你好'}).status_code == 200


def test_timeout_does_not_retry_or_fallback(tmp_path, monkeypatch):
    rt = MediaRuntime(tmp_path / 'config.json'); instance(rt); instance(rt, 'qwen')
    calls = []
    def handle(req):
        calls.append(req)
        raise httpx.ReadTimeout('timeout', request=req)
    mock(monkeypatch, handle)
    with pytest.raises(MediaError, match='可能仍在生成'):
        rt.submit('image', 'generate_image', ImageRequest('draw', tmp_path / 'out.png'))
    assert len(calls) == 1


def test_url_download_does_not_forward_api_key(tmp_path, monkeypatch):
    rt = MediaRuntime(tmp_path / 'config.json'); instance(rt)
    def handle(req):
        if req.url.host == 'cdn.test':
            assert 'authorization' not in req.headers
            return httpx.Response(200, content=base64.b64decode(encoded()))
        assert req.headers['authorization'] == 'Bearer private'
        return httpx.Response(200, json={'data': [{'url': 'https://cdn.test/image.png'}]})
    seen = []
    def factory(settings):
        seen.append(settings)
        headers = {'Authorization': 'Bearer private'} if len(seen) == 1 else {}
        assert len(seen) == 1 or settings['api_key_env'] == ''
        return httpx.Client(transport=httpx.MockTransport(handle), headers=headers)
    monkeypatch.setattr(image, 'client', factory)
    rt.submit('image', 'generate_image', ImageRequest('draw', tmp_path / 'out.png'))
    assert (tmp_path / 'out.png').is_file()


@pytest.mark.parametrize('auto,editing,expected_size', [
    (True, True, 'auto'),
    (True, False, '1536x1536'),
    (False, True, '1536x1536'),
])
def test_edit_auto_size_is_scoped_to_configured_edit_requests(
        tmp_path, monkeypatch, auto, editing, expected_size):
    import json
    from email.parser import BytesParser
    from email.policy import default

    rt = MediaRuntime(tmp_path / 'config.json')
    provider = instance(rt, edit=True)
    provider['settings']['edit_size_auto'] = auto
    rt.save_provider(provider)
    source = tmp_path / 'input.png'
    source.write_bytes(base64.b64decode(encoded()))

    def handle(req):
        if editing:
            assert req.url.path == '/v1/images/edits'
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + req.headers['content-type'] + '\r\n\r\n').encode() + req.content)
            parts = {p.get_param('name', header='content-disposition'): p.get_payload(decode=True)
                     for p in message.iter_parts()}
            assert parts['size'].decode() == expected_size
            assert parts['image'] == source.read_bytes()
        else:
            assert req.url.path == '/v1/images/generations'
            assert json.loads(req.content)['size'] == expected_size
        return httpx.Response(200, json={'data': [{'b64_json': encoded()}]})

    mock(monkeypatch, handle)
    result = rt.submit('image', 'generate_image', ImageRequest(
        'change background', tmp_path / 'out.png', size='1536x1536',
        image=source if editing else None))
    assert Path(result['outputs'][0]).is_file()
