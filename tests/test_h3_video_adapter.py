"""H3 requests, persistent jobs, atomic downloads and legacy video dispatch."""
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/media-adapters/src'))
from easel_media_adapters import MediaError, MediaRuntime, VideoRequest
from easel_media_adapters import h3


def setup(tmp_path, variant='fl2va'):
    rt = MediaRuntime(tmp_path / 'providers.json')
    p = rt.save_provider({'id': variant, 'name': variant, 'adapter': 'h3-video',
                         'settings': {'base_url': 'http://h3.test/v1', 'variant': variant}}, ['video'])
    req = VideoRequest('cat blinks', tmp_path / 'clip.mp4', ratio='16:9', seed=7)
    return rt, p, req


@pytest.fixture
def media(tmp_path, monkeypatch):
    png = tmp_path / 'cat.png'; png.write_bytes(b'png')
    monkeypatch.setattr(h3, 'media_info', lambda p: {
        'streams': [{'codec_type': 'audio' if p.suffix == '.wav' else 'video', 'codec_name': 'png'}],
        'format': {'duration': '5'}})
    return png


@pytest.mark.parametrize('kind,task,frames', [('text', 't2va', []), ('first', 'fl2va', [0]),
                                           ('last', 'fl2va', [-1]), ('both', 'fl2va', [0, -1])])
def test_fl_payload(tmp_path, media, kind, task, frames):
    rt, p, r = setup(tmp_path)
    r = replace(r, first_frame=media if kind in ('first', 'both') else None,
                last_frame=media if kind in ('last', 'both') else None)
    body = rt.adapters['h3-video'].payload(p, r)
    assert body['task'] == task
    assert [c['frame_index'] for c in body['conditions']] == frames
    assert all(c['uri'].startswith('data:image/png;base64,') for c in body['conditions'])
    assert body['target'] == {'short_edge': 768, 'aspect_ratio': '16:9', 'duration_seconds': 5}
    assert body['num_inference_steps'] == 9 and body['flow_shift'] == 6


def test_ref_mixed_payload(tmp_path, media):
    rt, p, r = setup(tmp_path, 'ref2va')
    video = tmp_path / 'ref.mp4'; video.write_bytes(b'video')
    audio = tmp_path / 'ref.wav'; audio.write_bytes(b'audio')
    r = replace(r, reference_images=(media, media), reference_videos=(video,), reference_audio=(audio,))
    body = rt.adapters['h3-video'].payload(p, r)
    assert body['model'] == 'MiniMax-H3-Ref2VA-Turbo'
    assert body['task'] == 'ref2va' and body['flow_shift'] == 12
    assert [c['type'] for c in body['conditions']] == ['image', 'image', 'video', 'audio']
    assert all(c['role'] == 'reference' and 'frame_index' not in c for c in body['conditions'])


@pytest.mark.parametrize('change', [{'duration': 3}, {'audio': 'off'}, {'ratio': 'bogus'},
                                  {'reference_images': (Path('absent.png'),)}, {'seed': -1}])
def test_invalid_inputs_never_submit(tmp_path, change, monkeypatch):
    rt, p, r = setup(tmp_path)
    monkeypatch.setattr(h3.H3Adapter, 'client', lambda *a: pytest.fail('must reject before network'))
    with pytest.raises(MediaError):
        rt.submit('video', 'generate_video', replace(r, **change))
    assert not r.output.exists()


def test_ref_requires_references(tmp_path):
    rt, p, r = setup(tmp_path, 'ref2va')
    with pytest.raises(MediaError, match='至少'):
        rt.submit('video', 'generate_video', r)


def test_ref_duration_limits(tmp_path, media, monkeypatch):
    rt, p, r = setup(tmp_path, 'ref2va')
    a = tmp_path / 'ref.wav'; a.write_bytes(b'audio')
    monkeypatch.setattr(h3, 'media_info', lambda p: {'streams': [{'codec_type': 'audio'}], 'format': {'duration': '6'}})
    with pytest.raises(MediaError, match='总时长'):
        rt.submit('video', 'generate_video', replace(r, reference_audio=(a,a,a)))


def test_submit_poll_download_and_resume(tmp_path, media, monkeypatch):
    rt, p, r = setup(tmp_path)
    requests = []
    statuses = iter(['in_progress', 'completed', 'completed'])
    def handler(req):
        requests.append((req.method, req.url.path))
        if req.method == 'POST':
            body = json.loads(req.content)
            assert body['task'] == 'fl2va'
            return httpx.Response(200, json={'id': 'video-1'})
        if req.url.path.endswith('/content'):
            return httpx.Response(200, content=b'mp4-video')
        return httpx.Response(200, json={'status': next(statuses)})
    monkeypatch.setattr(h3.H3Adapter, 'client', lambda *a: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(h3.time, 'sleep', lambda n: None)
    r = replace(r, first_frame=media)
    result = rt.submit('video', 'generate_video', r)
    assert result['id'] == 'video-1' and result['backend'] == 'http://h3.test/v1'
    assert r.output.read_bytes() == b'mp4-video'
    record = json.loads(Path(str(r.output)+'.job.json').read_text())
    assert 'conditions' not in record['request']
    rt.submit('video', 'generate_video', replace(r, resume=True))
    assert requests.count(('POST', '/v1/videos')) == 1
    with pytest.raises(MediaError, match='已有任务'):
        rt.submit('video', 'generate_video', r)


def test_failure_retains_id_without_output(tmp_path, monkeypatch):
    rt, p, r = setup(tmp_path)
    seen = []
    def handler(req):
        seen.append(req.method)
        return httpx.Response(200, json={'id': 'video-2'} if req.method == 'POST' else {'status': 'failed'})
    monkeypatch.setattr(h3.H3Adapter, 'client', lambda *a: httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MediaError, match='failed'):
        rt.submit('video', 'generate_video', r)
    assert not r.output.exists()
    assert json.loads(Path(str(r.output)+'.job.json').read_text())['id'] == 'video-2'
    assert seen.count('POST') == 1


def test_unknown_submission_is_not_repeated(tmp_path, monkeypatch):
    rt, p, r = setup(tmp_path)
    def handler(req):
        raise httpx.ReadTimeout('lost reply')
    monkeypatch.setattr(h3.H3Adapter, 'client', lambda *a: httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MediaError, match='未知'):
        rt.submit('video', 'generate_video', r)
    with pytest.raises(MediaError, match='已有任务'):
        rt.submit('video', 'generate_video', r)
    assert not r.output.exists()


def test_video_cli_default_and_explicit_legacy(tmp_path, monkeypatch):
    rt, p, r = setup(tmp_path)
    monkeypatch.setenv('EASEL_MEDIA_CONFIG', str(rt.path))
    monkeypatch.delenv('VIDEO_PROVIDER', raising=False)
    sys.path.insert(0, str(ROOT / 'skills/shared/scripts'))
    spec = importlib.util.spec_from_file_location('h3_video_cli', ROOT / 'skills/shared/scripts/ai_video.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.resolve_provider(None) == 'fl2va'
    assert module.resolve_provider('ark') == 'ark'
    assert module.provider_capabilities('fl2va')['native_audio'] is True


def test_poll_timeout_can_resume_without_post(tmp_path, media, monkeypatch):
    rt, p, r = setup(tmp_path)
    seen = []
    complete = False
    def handler(req):
        seen.append(req.method)
        if req.method == 'POST':
            return httpx.Response(200, json={'id': 'video-timeout'})
        if req.url.path.endswith('/content'):
            return httpx.Response(200, content=b'mp4')
        return httpx.Response(200, json={'status': 'completed' if complete else 'in_progress'})
    monkeypatch.setattr(h3.H3Adapter, 'client', lambda *a: httpx.Client(transport=httpx.MockTransport(handler)))
    clock = iter([0, 0, 0, 3, 4, 4])
    monkeypatch.setattr(h3.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(h3.time, 'sleep', lambda n: None)
    with pytest.raises(MediaError, match='等待超时'):
        rt.submit('video', 'generate_video', replace(r, timeout=1))
    complete = True
    rt.submit('video', 'generate_video', replace(r, resume=True))
    assert seen.count('POST') == 1
    assert r.output.exists()


def test_bad_download_is_atomic(tmp_path, monkeypatch):
    rt, p, r = setup(tmp_path)
    def handler(req):
        if req.method == 'POST':
            return httpx.Response(200, json={'id': 'video-bad'})
        if req.url.path.endswith('/content'):
            return httpx.Response(200, content=b'not a video')
        return httpx.Response(200, json={'status': 'completed'})
    monkeypatch.setattr(h3.H3Adapter, 'client', lambda *a: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(h3, 'media_info', lambda p: {'streams': []})
    with pytest.raises(MediaError, match='视频流'):
        rt.submit('video', 'generate_video', r)
    assert not r.output.exists()
    assert not list(tmp_path.glob('.video-*'))


def test_switching_default_does_not_change_asr(tmp_path):
    rt, p, r = setup(tmp_path)
    rt.save_provider({'id': 'asr', 'name': 'ASR', 'adapter': 'openai-transcription',
                      'settings': {'base_url': 'http://asr.test/v1', 'model': 'asr'}}, ['transcribe'])
    rt.clear_default('video')
    assert rt.load()['defaults'] == {'transcribe': 'asr'}
    assert rt.resolve('video', 'fl2va')[0]['id'] == 'fl2va'


def test_web_video_defaults_and_legacy_switch(tmp_path, monkeypatch):
    import asyncio
    sys.path.insert(0, str(ROOT / 'web'))
    import app as web
    rt, p, r = setup(tmp_path)
    monkeypatch.setattr(web, '_media_runtime', lambda: rt)
    monkeypatch.setattr(web, '_read_env', lambda: {'VIDEO_PROVIDER': 'ark'})
    monkeypatch.setattr(web, '_oc_config_path', lambda: tmp_path / 'no-openclaw.json')
    assert all(row['role'] == '备' for row in web._model_channels()['channels']['video']['rows'])
    updates = []
    monkeypatch.setattr(web, '_write_env_direct', lambda d: updates.append(d))
    req = web.ModelSaveRequest(channel='video', rows=[{'slot': 'ark', 'primary': True}])
    data = asyncio.run(web.api_settings_models_save(req))
    assert updates[-1]['VIDEO_PROVIDER'] == 'ark'
    assert 'video' not in rt.load()['defaults']
    assert next(row for row in data['channels']['video']['rows'] if row['slot']=='ark')['role'] == '主'
