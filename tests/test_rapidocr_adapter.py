
import httpx
import pytest
from PIL import Image
from easel_media_adapters import MediaError, MediaRuntime, OCRRequest
from easel_media_adapters.rapidocr import RapidOCRAdapter


def setup(tmp_path):
    adapter = RapidOCRAdapter()
    runtime = MediaRuntime(tmp_path / 'config.json', {'rapidocr': adapter})
    provider = runtime.save_provider({'id': 'ocr-local', 'name': 'OCR', 'adapter': 'rapidocr',
                                     'settings': {'base_url': 'http://ocr.test'}}, ['ocr'])
    source = tmp_path / 'image.png'
    Image.new('RGB', (200, 100), 'white').save(source)
    result = {'text': 'hello', 'items': [{'text': 'hello', 'score': .9,
              'box': [[1, 1], [100, 1], [100, 30], [1, 30]]}], 'image': {'width': 200, 'height': 100}}
    return adapter, runtime, provider, source, result


def client(monkeypatch, adapter, handler):
    monkeypatch.setattr(adapter, 'client', lambda p: httpx.Client(transport=httpx.MockTransport(handler)))


def test_upload_and_normalization(tmp_path, monkeypatch):
    adapter, runtime, provider, source, result = setup(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == '/ocr'
        assert b'name="image_file"' in request.content
        assert b'image/png' in request.content
        return httpx.Response(200, json=result)
    client(monkeypatch, adapter, handler)
    out = runtime.submit('ocr', 'recognize_text', OCRRequest(source))
    assert out['text'] == 'hello' and out['raw'] == result
    assert out['coordinate_space'] == 'exif_transposed_pixels'
    assert out['provider'] == provider['id'] and len(requests) == 1


@pytest.mark.parametrize('mutation', [
    lambda r: r.pop('text'), lambda r: r.pop('items'),
    lambda r: r['items'][0].pop('score'),
    lambda r: r['items'][0].update(score=float('nan')),
    lambda r: r['items'][0].update(score=True),
    lambda r: r['items'][0].update(box=[[1, 2]]),
    lambda r: r['image'].update(width=100),
    lambda r: r.update(items=[]),
])
def test_invalid_success_rejected(tmp_path, mutation):
    *_, result = setup(tmp_path)
    mutation(result)
    with pytest.raises(MediaError):
        RapidOCRAdapter.validate_result(result, 200, 100)


def test_empty_text_is_valid(tmp_path, monkeypatch):
    adapter, runtime, _, source, result = setup(tmp_path)
    result.update(text='', items=[])
    client(monkeypatch, adapter, lambda r: httpx.Response(200, json=result))
    out = runtime.submit('ocr', 'recognize_text', OCRRequest(source))
    assert out['warnings'] == ['未检测到文字']


@pytest.mark.parametrize('status', [422, 429, 500, 302])
def test_no_retry_on_service_error(tmp_path, monkeypatch, status):
    adapter, runtime, _, source, _ = setup(tmp_path)
    calls = []
    client(monkeypatch, adapter, lambda r: (calls.append(r) or httpx.Response(status)))
    with pytest.raises(MediaError, match='HTTP'):
        runtime.submit('ocr', 'recognize_text', OCRRequest(source))
    assert len(calls) == 1


def test_timeout_no_retry(tmp_path, monkeypatch):
    adapter, runtime, _, source, _ = setup(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout')
    client(monkeypatch, adapter, handler)
    with pytest.raises(MediaError, match='超时'):
        runtime.submit('ocr', 'recognize_text', OCRRequest(source))
    assert len(calls) == 1


def test_invalid_input_before_network(tmp_path, monkeypatch):
    adapter, runtime, _, source, _ = setup(tmp_path)
    source.write_text('not image')
    client(monkeypatch, adapter, lambda r: pytest.fail('must not upload'))
    with pytest.raises(MediaError):
        runtime.submit('ocr', 'recognize_text', OCRRequest(source))


def test_exif_rotated_coordinates(tmp_path, monkeypatch):
    adapter, runtime, _, source, result = setup(tmp_path)
    source = tmp_path / 'rotated.jpg'
    exif = Image.Exif(); exif[274] = 6
    Image.new('RGB', (100, 200), 'white').save(source, exif=exif)
    client(monkeypatch, adapter, lambda r: httpx.Response(200, json=result))
    out = runtime.submit('ocr', 'recognize_text', OCRRequest(source))
    assert out['source_exif_orientation'] == 6
    assert out['image'] == {'width': 200, 'height': 100}


def test_configuration_other_defaults_preserved(tmp_path):
    adapter, runtime, provider, _, _ = setup(tmp_path)
    data = runtime.load(); data['defaults']['video'] = 'existing-video'; runtime._write(data)
    runtime.save_provider(provider, ['ocr'])
    assert runtime.load()['defaults']['video'] == 'existing-video'


def test_oversized_before_network(tmp_path, monkeypatch):
    from easel_media_adapters import rapidocr
    adapter, runtime, _, source, _ = setup(tmp_path)
    monkeypatch.setattr(rapidocr, 'MAX_BYTES', 10)
    client(monkeypatch, adapter, lambda r: pytest.fail('must not upload'))
    with pytest.raises(MediaError, match='MiB'):
        runtime.submit('ocr', 'recognize_text', OCRRequest(source))


def test_multiframe_rejected(tmp_path, monkeypatch):
    adapter, runtime, _, _, _ = setup(tmp_path)
    source = tmp_path / 'multipage.tiff'
    images = [Image.new('RGB', (100, 100), 'white'), Image.new('RGB', (100, 100), 'black')]
    images[0].save(source, save_all=True, append_images=images[1:])
    client(monkeypatch, adapter, lambda r: pytest.fail('must not upload'))
    with pytest.raises(MediaError, match='单帧'):
        runtime.submit('ocr', 'recognize_text', OCRRequest(source))


def test_malformed_json_is_error(tmp_path, monkeypatch):
    adapter, runtime, _, source, _ = setup(tmp_path)
    client(monkeypatch, adapter, lambda r: httpx.Response(200, text='not JSON'))
    with pytest.raises(MediaError, match='JSON'):
        runtime.submit('ocr', 'recognize_text', OCRRequest(source))


def test_web_configuration_supports_ocr(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from web.app import app
    monkeypatch.setenv('EASEL_MEDIA_CONFIG', str(tmp_path / 'media.json'))
    with TestClient(app, base_url='http://localhost', headers={'Origin': 'http://localhost:7860'}) as web:
        data = web.get('/api/settings/media').json()
        assert any(d['id'] == 'rapidocr' and d['channels'] == ['ocr'] for d in data['adapters'])
        response = web.post('/api/settings/media', json={'provider': {
            'id': 'ocr-local', 'name': 'OCR', 'adapter': 'rapidocr',
            'settings': {'base_url': 'http://ocr.test'}}, 'defaultChannels': ['ocr']})
        assert response.status_code == 200
        assert response.json()['defaults']['ocr'] == 'ocr-local'


def test_current_server_reports_original_dimensions(tmp_path, monkeypatch):
    adapter, runtime, _, _, result = setup(tmp_path)
    source = tmp_path / 'rotated.jpg'
    exif = Image.Exif(); exif[274] = 6
    Image.new('RGB', (100, 200), 'white').save(source, exif=exif)
    result['image'] = {'width': 100, 'height': 200}
    client(monkeypatch, adapter, lambda r: httpx.Response(200, json=result))
    out = runtime.submit('ocr', 'recognize_text', OCRRequest(source))
    assert out['image'] == {'width': 200, 'height': 100}
    assert out['raw']['image'] == {'width': 100, 'height': 200}
    assert 'EXIF' in out['warnings'][0]
