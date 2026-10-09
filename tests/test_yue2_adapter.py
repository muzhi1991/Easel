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
    {'instrumental':True},{'duration':0},{'lyrics':''},{'model':'other'},
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


@pytest.mark.parametrize('instrumental', [False, True])
def test_target_duration_and_instrumental_protocol(tmp_path, monkeypatch, flac, instrumental):
    rt, p, r = setup(tmp_path, monkeypatch)
    r = MusicRequest(**{**r.__dict__, 'instrumental': instrumental,
                        'lyrics': None if instrumental else r.lyrics, 'duration': 30.5})
    calls = []
    def handler(req):
        calls.append(req)
        if req.method == 'POST':
            body = json.loads(req.content)
            assert req.url.path == '/v1/jobs'
            assert body['duration_seconds'] == 30.5 and body['duration_mode'] == 'target'
            assert body.get('instrumental', False) == instrumental
            assert ('lyrics' not in body) if instrumental else bool(body['lyrics'])
            return httpx.Response(202, json={'id': 'job-1'})
        if req.url.path.endswith('/audio'): return httpx.Response(200, content=flac)
        if req.url.path.endswith('/score'): return httpx.Response(200, content=b'X:1\nK:C\nCDEF|')
        return httpx.Response(200, json=finished())
    mock(monkeypatch, handler)
    result = rt.submit('music', 'generate_music', r)
    assert result['duration_target'] == 30.5
    assert result['duration_actual'] == .2 and result['duration_deviation'] == pytest.approx(-30.3)
    # Target mismatch is reported, not silently trimmed, stretched or called failure.
    assert result['audio']['duration'] == .2
    assert sum(c.method == 'POST' for c in calls) == 1


@pytest.mark.parametrize('instrumental', [False, True])
def test_cover_multipart_digest_and_resume_without_source(tmp_path, monkeypatch, flac, instrumental):
    import hashlib
    from email.parser import BytesParser
    from email.policy import default
    rt, p, r = setup(tmp_path, monkeypatch)
    source = tmp_path / 'input.flac'; source.write_bytes(flac)
    r = MusicRequest(**{**r.__dict__, 'reference_audio': source, 'instrumental': instrumental,
                        'lyrics': None if instrumental else r.lyrics, 'duration': 30})
    calls = []
    def handler(req):
        calls.append(req)
        if req.method == 'POST':
            assert req.url.path == '/v1/covers' and 'Idempotency-Key' in req.headers
            msg = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + req.headers['content-type'] + '\r\n\r\n').encode() + req.content)
            fields = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
                      for part in msg.iter_parts()}
            assert fields['audio'] == flac and fields['seed'] == b'42'
            assert fields['duration_seconds'] == b'30' and fields['duration_mode'] == b'target'
            assert fields.get('instrumental', b'false') == (b'true' if instrumental else b'false')
            assert not {'abc', 'cot', 'n', 'model'} & fields.keys()
            assert ('lyrics' not in fields) if instrumental else bool(fields['lyrics'])
            return httpx.Response(202, json={'id': 'job-1'})
        if req.url.path.endswith('/audio'): return httpx.Response(200, content=flac)
        if req.url.path.endswith('/score'): return httpx.Response(200, content=b'X:1\nK:C\nCDEF|')
        return httpx.Response(200, json=finished())
    mock(monkeypatch, handler)
    result = rt.submit('music', 'generate_music', r)
    assert result['operation'] == 'cover'
    assert result['reference_audio']['sha256'] == hashlib.sha256(flac).hexdigest()
    assert result['reference_audio']['bytes'] == len(flac)
    source.unlink(); calls.clear()
    rt.submit('music', 'generate_music', MusicRequest('', r.output, resume=True))
    assert calls and all(req.method == 'GET' for req in calls)


@pytest.mark.parametrize('options', [
    {'duration': 9}, {'duration': 181}, {'duration': float('nan')}, {'duration': True},
    {'instrumental': True, 'lyrics': None, 'cot': 'off'},
    {'reference_audio': Path('missing'), 'abc': 'X:1\nK:C\nC'},
    {'reference_audio': Path('missing'), 'cot': 'melody'},
])
def test_extension_invalid_parameters_fail_before_submission(tmp_path, monkeypatch, options):
    rt, p, r = setup(tmp_path, monkeypatch)
    mock(monkeypatch, lambda req: pytest.fail('invalid input submitted'))
    with pytest.raises(MediaError):
        rt.submit('music', 'generate_music', MusicRequest(**{**r.__dict__, **options}))
    assert not r.output.with_suffix('.mp3.job.json').exists()


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'large', 'long'])
def test_invalid_reference_never_uploads_or_strands_record(tmp_path, monkeypatch, flac, kind):
    rt, p, r = setup(tmp_path, monkeypatch)
    source = tmp_path / 'reference.flac'
    if kind != 'missing': source.write_bytes(b'garbage' if kind == 'corrupt' else flac)
    if kind == 'large': monkeypatch.setattr(yue2, 'MAX_REFERENCE_BYTES', 1)
    if kind == 'long': monkeypatch.setattr(yue2, 'audio_info', lambda p: {'duration': 180.1})
    mock(monkeypatch, lambda req: pytest.fail('invalid reference uploaded'))
    with pytest.raises(MediaError):
        rt.submit('music', 'generate_music', MusicRequest(**{**r.__dict__, 'reference_audio': source}))
    assert not r.output.with_suffix('.mp3.job.json').exists()


def test_cli_wires_reference_and_target_but_resume_does_not_read_missing_inputs(tmp_path, monkeypatch):
    import easel.media as bridge
    rt, p, r = setup(tmp_path, monkeypatch)
    monkeypatch.setenv('EASEL_MEDIA_CONFIG', str(rt.path))
    m = music_cli(); calls = []
    def generate(*args, **options):
        calls.append(options)
        return {'provider': p['id'], 'model': 'YuE2-3B', 'id': 'job-1', 'audio': {'duration': 32},
                'output': str(r.output), 'duration_target': 30, 'duration_actual': 32, 'duration_deviation': 2}
    monkeypatch.setattr(bridge, 'generate_music', generate)
    assert m.main(['generate', '--prompt', 'piano', '--instrumental', '--duration', '30',
                   '--reference-audio', 'reference.flac', '-o', 'outputs/cover/song.mp3']) == 0
    assert calls[-1]['reference_audio'] == Path('reference.flac') and calls[-1]['duration'] == 30
    assert m.main(['generate', '--resume', '--lyrics-file', 'missing', '--abc-file', 'missing',
                   '--reference-audio', 'missing', '-o', 'outputs/cover/song.mp3']) == 0
    assert calls[-1]['reference_audio'] is None and calls[-1]['lyrics'] is None


def test_cover_unknown_submission_keeps_digest_and_never_reuploads(tmp_path, monkeypatch, flac):
    import hashlib
    rt, p, r = setup(tmp_path, monkeypatch)
    source = tmp_path / 'source.flac'; source.write_bytes(flac)
    r = MusicRequest(**{**r.__dict__, 'reference_audio': source})
    calls = []
    def handler(req):
        calls.append(req)
        assert req.url.path == '/v1/covers'
        saved = json.loads(r.output.with_suffix('.mp3.job.json').read_text())
        assert saved['reference_audio']['sha256'] == hashlib.sha256(flac).hexdigest()
        assert saved['idempotency_key'] == req.headers['Idempotency-Key']
        raise httpx.ReadTimeout('unknown submit status', request=req)
    mock(monkeypatch, handler)
    with pytest.raises(MediaError, match='不自动重交'):
        rt.submit('music', 'generate_music', r)
    assert len(calls) == 1
    source.unlink(); calls.clear()
    with pytest.raises(MediaError, match='无ID'):
        rt.submit('music', 'generate_music', MusicRequest('', r.output, resume=True))
    assert not calls
