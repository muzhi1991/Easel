"""Protocol, recovery, and failure semantics without real model/network calls."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/media-adapters/src'))
sys.path.insert(0, str(ROOT / 'skills/shared/scripts'))
from easel_media_adapters import MediaError, MediaRuntime, MusicRequest
from easel_media_adapters import yue2


@pytest.fixture(scope='module')
def flac(tmp_path_factory):
    out = tmp_path_factory.mktemp('music-fixture') / 'sample.flac'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.2',
                    '-ar','48000','-ac','2',str(out)],check=True,capture_output=True)
    return out.read_bytes()


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('EASEL_MEDIA_MUSIC_KEY','secret-for-test')
    rt = MediaRuntime(tmp_path/'config.json')
    p = rt.save_provider({'id':'music-local','name':'Local music','adapter':'yue2-music',
                         'settings':{'base_url':'http://music.test','api_key_env':'EASEL_MEDIA_MUSIC_KEY'}},['music'])
    return rt,p,MusicRequest('Mandarin piano pop',tmp_path/'song.mp3',lyrics='[Verse]\n晚风吹来',seed=42)


def mock(monkeypatch, handler):
    monkeypatch.setattr(yue2, 'client', lambda s: httpx.Client(
        headers={'Authorization':'Bearer secret-for-test'}, transport=httpx.MockTransport(handler)))


def finished(status='succeeded', flags=None):
    return {'id':'job-1','status':status,'stage':'finished','result':{
        'audio_seconds':.2,'truncated':flags if flags is not None else {'abc':False,'semantic':False}}}


def good_handler(flac, calls):
    def handler(req):
        calls.append(req)
        assert req.headers['authorization']=='Bearer secret-for-test'
        if req.method=='POST':
            body=json.loads(req.content)
            assert set(body)=={'style','lyrics','cot','seed','n'}
            assert body['seed']==42 and body['n']==1
            assert 'Idempotency-Key' in req.headers
            return httpx.Response(202,json={'id':'job-1','status':'queued'})
        if req.url.path.endswith('/audio'):return httpx.Response(200,content=flac)
        if req.url.path.endswith('/score'):return httpx.Response(200,content=b'X:1\nK:C\nCDEF|')
        return httpx.Response(200,json=finished())
    return handler


def test_real_flac_decode_mp3_score_and_resume_without_post(tmp_path,monkeypatch,flac):
    rt,p,r=setup(tmp_path,monkeypatch);calls=[]
    mock(monkeypatch,good_handler(flac,calls))
    result=rt.submit('music','generate_music',r)
    assert result['audio']['duration']==.2
    assert result['audio']['sample_rate']==48000 and result['audio']['channels']==2
    assert r.output.is_file() and r.output.with_suffix('.flac').read_bytes()==flac
    assert r.output.with_suffix('.abc').is_file()
    text=r.output.with_suffix('.mp3.job.json').read_text()
    assert 'secret-for-test' not in text and 'idempotency_key' in text
    calls.clear()
    rt.submit('music','generate_music',MusicRequest('',r.output,resume=True))
    assert all(c.method=='GET' for c in calls)
    with pytest.raises(MediaError,match='已存在'):rt.submit('music','generate_music',r)


@pytest.mark.parametrize('options',[
    {'instrumental':True},{'duration':30},{'lyrics':''},{'model':'other'},
    {'seed':-1},{'seed':2**63},{'cot':'off','abc':'X:1\nK:C\nC'},
    {'prompt':'x'*2001},{'lyrics':'x'*16001},
])
def test_unsupported_inputs_never_submit(tmp_path,monkeypatch,options):
    rt,p,r=setup(tmp_path,monkeypatch)
    values={**r.__dict__,**options}
    mock(monkeypatch,lambda req:pytest.fail('invalid request reached network'))
    with pytest.raises(MediaError):rt.submit('music','generate_music',MusicRequest(**values))
    assert not r.output.exists() and not r.output.with_suffix('.mp3.job.json').exists()


@pytest.mark.parametrize('status,flags',[
    ('truncated',None),('failed',None),('cancelled',None),('mystery',None),
    ('succeeded',{'abc':False,'semantic':True}),('succeeded',{}),
])
def test_terminal_errors_never_download(tmp_path,monkeypatch,status,flags):
    rt,p,r=setup(tmp_path,monkeypatch);calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='POST':return httpx.Response(202,json={'id':'job-1'})
        assert req.url.path.endswith('/job-1')
        return httpx.Response(200,json=finished(status,flags))
    mock(monkeypatch,handler)
    with pytest.raises(MediaError):rt.submit('music','generate_music',r)
    assert len(calls)==2 and not r.output.exists()
    assert json.loads(r.output.with_suffix('.mp3.job.json').read_text())['id']=='job-1'


@pytest.mark.parametrize('post_status',[401,429,503])
def test_submission_failures_do_not_retry(tmp_path,monkeypatch,post_status):
    rt,p,r=setup(tmp_path,monkeypatch);calls=[]
    mock(monkeypatch,lambda req:(calls.append(req) or httpx.Response(post_status,json={'error':'busy'})))
    with pytest.raises(MediaError):rt.submit('music','generate_music',r)
    assert len(calls)==1 and calls[0].method=='POST'
    calls.clear()
    with pytest.raises(MediaError,match='无ID'):
        rt.submit('music','generate_music',MusicRequest('',r.output,resume=True))
    assert not calls


def test_missing_credential_does_not_strand_task_record(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path,monkeypatch)
    monkeypatch.delenv('EASEL_MEDIA_MUSIC_KEY')
    with pytest.raises(MediaError,match='凭证'):rt.submit('music','generate_music',r)
    assert not r.output.with_suffix('.mp3.job.json').exists()


def test_fake_audio_preserves_existing_files_on_resume(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path,monkeypatch)
    record={'provider':p['id'],'adapter':'yue2-music','base_url':p['settings']['base_url'],
            'output':str(r.output),'request':{'cot':'full'},'id':'job-1'}
    r.output.with_suffix('.mp3.job.json').write_text(json.dumps(record))
    r.output.write_bytes(b'previous-good-audio')
    def handler(req):
        if req.url.path.endswith('/audio'):return httpx.Response(200,json={'error':'not audio'})
        return httpx.Response(200,json=finished())
    mock(monkeypatch,handler)
    with pytest.raises(MediaError,match='FLAC'):rt.submit('music','generate_music',MusicRequest('',r.output,resume=True))
    assert r.output.read_bytes()==b'previous-good-audio'


def test_timeout_retains_id_for_recovery(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path,monkeypatch);calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(202,json={'id':'job-1','status':'queued'})
    mock(monkeypatch,handler)
    with pytest.raises(MediaError,match='等待超时'):
        rt.submit('music','generate_music',MusicRequest(**{**r.__dict__,'timeout':.001}))
    assert sum(c.method=='POST' for c in calls)==1
    assert json.loads(r.output.with_suffix('.mp3.job.json').read_text())['id']=='job-1'


def test_resume_wrong_provider_or_url_never_submits(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path,monkeypatch)
    r.output.with_suffix('.mp3.job.json').write_text(json.dumps({'provider':'different'}))
    mock(monkeypatch,lambda req:pytest.fail('wrong resume made a request'))
    with pytest.raises(MediaError,match='恢复供应商'):rt.submit('music','generate_music',MusicRequest('',r.output,resume=True))


def test_probe_checks_auth_without_creating_job(tmp_path,monkeypatch):
    rt,p,r=setup(tmp_path,monkeypatch);calls=[]
    def handler(req):
        calls.append(req);assert req.method=='GET'
        return httpx.Response(200,json={'status':'ready'}) if req.url.path.startswith('/health') else httpx.Response(401)
    mock(monkeypatch,handler)
    assert rt.probe(p['id'])['ok'] is False and len(calls)==2


def music_cli():
    spec=importlib.util.spec_from_file_location('music_adapter_test',ROOT/'skills/shared/scripts/ai_music.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_default_dispatch_and_failure_never_falls_back(tmp_path,monkeypatch):
    import easel.media as bridge
    rt,p,r=setup(tmp_path,monkeypatch);monkeypatch.setenv('EASEL_MEDIA_CONFIG',str(rt.path))
    m=music_cli()
    monkeypatch.setattr(bridge,'generate_music',lambda *a,**k:(_ for _ in ()).throw(MediaError('generation failed')))
    for name in m.PROVIDER_GENERATORS:monkeypatch.setitem(m.PROVIDER_GENERATORS,name,lambda a:pytest.fail('no fallback'))
    assert m.resolve_provider(None)==p['id']
    assert m.resolve_provider('suno-compatible')=='suno-compatible'
    with pytest.raises(SystemExit):m.main(['generate','--prompt','pop','--lyrics','词','-o','outputs/音乐失败验收/song.mp3'])


def test_ui_legacy_selection_clears_only_music(tmp_path,monkeypatch):
    import web.app as web
    from fastapi.testclient import TestClient
    rt,p,r=setup(tmp_path,monkeypatch)
    d=rt.load();d['defaults']['speech']='tts-local';rt._write(d)
    env=tmp_path/'.env';env.write_text('MUSIC_PROVIDER=suno-compatible\nMUSIC_API_KEY=test-key\nMUSIC_BASE_URL=http://old.test\n')
    monkeypatch.setattr(web,'ENV_FILE',env)
    monkeypatch.setattr(web,'_media_runtime',lambda:rt)
    with TestClient(web.app,base_url='http://127.0.0.1:7860',client=('127.0.0.1',51234)) as c:
        rows=c.get('/api/settings/models').json()['channels']['music']['rows']
        assert not any(row['role']=='主' for row in rows)
        r=c.post('/api/settings/models/save',json={'channel':'music','rows':[{'slot':'suno-compatible','primary':True}]})
        assert r.status_code==200,r.text
    assert rt.load()['defaults']=={'speech':'tts-local'}


def test_web_loads_only_media_env_without_execution_or_overriding(monkeypatch, tmp_path):
    import types
    from easel import cli
    (tmp_path / 'web').mkdir()
    (tmp_path / 'web/app.py').touch()
    (tmp_path / '.env').write_text("EASEL_MEDIA_TEST_KEY='local-key'\n"
        "EASEL_MEDIA_EXISTING=changed\nOPENAI_API_KEY=unrelated\n"
        "EASEL_MEDIA_LITERAL=$(touch forbidden)\n")
    monkeypatch.setattr(cli, 'PROJECT_ROOT', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('EASEL_MEDIA_EXISTING', 'inherited')
    captured = {}
    def run(*args, **kwargs):
        captured.update(kwargs['env'])
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(cli.subprocess, 'run', run)
    assert cli.cmd_web(types.SimpleNamespace(port=7860)) == 0
    assert captured['EASEL_MEDIA_TEST_KEY'] == 'local-key'
    assert captured['EASEL_MEDIA_EXISTING'] == 'inherited'
    assert captured['EASEL_MEDIA_LITERAL'] == '$(touch forbidden)'
    assert 'OPENAI_API_KEY' not in captured
