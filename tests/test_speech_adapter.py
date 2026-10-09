import importlib.util
import io
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'integrations/media-adapters/src'))
sys.path.insert(0,str(ROOT / 'skills/shared/scripts'))
from easel_media_adapters import MediaError, MediaRuntime, SpeechRequest
from easel_media_adapters import speech


def wav():
    b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\0\0'*2400)
    return b.getvalue()


def setup(tmp_path):
    rt=MediaRuntime(tmp_path/'config.json')
    p=rt.save_provider({'id':'tts-local','name':'Local','adapter':'openai-speech','settings':{
        'base_url':'http://tts.test/v1','model':'qwen3-tts','voice':'vivian',
        'language':'Chinese','expected_model_root':'CustomVoice'}},['speech'])
    return rt,p,SpeechRequest('你好',tmp_path/'out.wav')


def mock(monkeypatch, handler):
    monkeypatch.setattr(speech,'client',lambda s:httpx.Client(transport=httpx.MockTransport(handler)))


def test_customvoice_request_and_real_wav(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path);calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':'qwen3-tts','root':'Qwen-1.7B-CustomVoice'}]})
        payload=json.loads(req.content)
        assert payload=={'model':'qwen3-tts','input':'你好','voice':'vivian','response_format':'wav','language':'Chinese'}
        assert 'authorization' not in req.headers
        return httpx.Response(200,content=wav())
    mock(monkeypatch,handler)
    result=rt.submit('speech','generate_speech',r)
    assert result['duration']==.1 and r.output.read_bytes()==wav()
    assert len(calls)==2


def test_wrong_mode_never_submits(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path);methods=[]
    def handler(req):
        methods.append(req.method)
        return httpx.Response(200,json={'data':[{'id':'qwen3-tts','root':'Qwen-Base'}]})
    mock(monkeypatch,handler)
    with pytest.raises(MediaError,match='权重模式'):rt.submit('speech','generate_speech',r)
    assert methods==['GET'] and not r.output.exists()


@pytest.mark.parametrize('body,status',[(b'{"error":"failed"}',200),(b'',200),(wav()[:-20],200),(b'busy',429)])
def test_failed_audio_preserves_existing_output(tmp_path,monkeypatch,body,status):
    rt,p,r=setup(tmp_path);p['settings']['expected_model_root']='';rt.save_provider(p)
    r.output.write_bytes(b'previous-good-file')
    calls=[]
    def handler(req):
        calls.append(req);return httpx.Response(status,content=body)
    mock(monkeypatch,handler)
    with pytest.raises(MediaError):rt.submit('speech','generate_speech',r)
    assert len(calls)==1 and r.output.read_bytes()==b'previous-good-file'


def tts():
    spec=importlib.util.spec_from_file_location('tts_speech_test',ROOT/'skills/shared/scripts/tts.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_sentences_real_timestamps_voice_and_style(tmp_path,monkeypatch):
    import easel.media as media
    import output_paths
    m=tts();calls=[]
    monkeypatch.setattr(output_paths,'validate_output_path',lambda p:Path(p))
    def generate(text,out,**kw):
        calls.append((text,kw));out.write_bytes(wav())
        return {'provider':'local','model':'qwen3-tts','voice':kw['voice'],'duration':.1}
    monkeypatch.setattr(media,'generate_speech',generate)
    out=tmp_path/'voice.wav';sub=tmp_path/'voice.srt'
    result=m._run_adapter('你好。再见。',out,'wav',sub,'serena','local','自然')
    assert len(calls)==2 and calls[0][1]['voice']=='serena' and calls[0][1]['instructions']=='自然'
    assert result['segments'][1]['start']==.1 and result['duration']==.2
    assert '00:00:00,100 --> 00:00:00,200' in sub.read_text()
    with wave.open(str(out)) as w:assert w.getnframes()==4800
    assert out.with_suffix('.tts.json').exists()


def test_adapter_failure_never_runs_edge(tmp_path,monkeypatch):
    m=tts()
    monkeypatch.setattr(m,'_speech_default',lambda:'local')
    monkeypatch.setattr(m,'_run_adapter',lambda *a:(_ for _ in ()).throw(MediaError('upstream down')))
    monkeypatch.setattr(m,'_run_closed',lambda *a:pytest.fail('No legacy fallback'))
    monkeypatch.setattr(m,'_run_edge_tts',lambda *a,**kw:pytest.fail('No edge fallback'))
    a=m.build_parser().parse_args(['speak','--text','你好','-o',str(tmp_path/'a.wav')])
    with pytest.raises(SystemExit) as e:m.cmd_speak(a)
    assert e.value.code==4


def test_speech_default_does_not_change_other_channels(tmp_path):
    rt,p,r=setup(tmp_path)
    d=rt.load();d['defaults']['ocr']='other';rt._write(d)
    assert rt.load()['defaults']=={'speech':'tts-local','ocr':'other'}


def test_ui_legacy_selection_clears_only_speech_default(tmp_path,monkeypatch):
    import web.app as web
    from fastapi.testclient import TestClient
    rt,p,r=setup(tmp_path)
    d=rt.load();d['defaults']['ocr']='ocr-local';rt._write(d)
    env=tmp_path/'.env';env.write_text('VOICE_PROVIDER=fish-audio\nFISH_API_KEY=test-key\n')
    monkeypatch.setattr(web,'ENV_FILE',env)
    monkeypatch.setattr(web,'_media_runtime',lambda:rt)
    with TestClient(web.app,base_url='http://127.0.0.1:7860',client=('127.0.0.1',51234)) as c:
        rows=c.get('/api/settings/models').json()['channels']['speech']['rows']
        assert not any(row['role']=='主' for row in rows)
        response=c.post('/api/settings/models/save',json={'channel':'speech','rows':[
            {'slot':'fish-audio','primary':True,'model':'s2.1-pro-free'}]})
        assert response.status_code==200,response.text
    assert rt.load()['defaults']=={'ocr':'ocr-local'}
