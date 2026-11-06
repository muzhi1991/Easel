"""Persona selection cannot borrow legacy credentials, browser sessions or caches."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from easel import account_scope
from easel.conversations import Conversations, Conflict, Missing
import web.app as web


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    token = account_scope.current_persona.set('')
    monkeypatch.setattr(web, 'LOGIN_DIR', tmp_path / '_login')
    monkeypatch.setattr(web, 'OUTPUTS_DIR', tmp_path)
    monkeypatch.setattr(web, 'BROWSER_PROFILES', tmp_path / 'browsers')
    monkeypatch.setattr(web, 'WECHAT_CONFIG_YAML', tmp_path / 'legacy.yaml')
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path / '_sessions')
    monkeypatch.setattr(web, 'LOGIN_PROCESSES', {})
    monkeypatch.setattr(web, '_WHOAMI_CACHE', {})
    monkeypatch.setattr(web, '_WHOAMI_TASKS', {})
    monkeypatch.setattr(web, 'profile_exists', lambda name: name in ('养生', '科技'))
    monkeypatch.setattr(web, '_proxy_env', lambda: {})
    yield
    account_scope.current_persona.reset(token)


def test_legacy_credentials_and_login_are_only_general():
    web._wechat_save_credentials('legacy-id', 'secret')
    web._write_login_marker('wechat-oa-mp', 'success')
    assert web._account_logged_in('wechat-oa', web.LOGIN_RUNNERS['wechat-oa'])
    account_scope.current_persona.set('养生')
    assert not web._wechat_has_credentials()
    assert not web._account_logged_in('wechat-oa', web.LOGIN_RUNNERS['wechat-oa'])
    web._wechat_save_credentials('herbal-id', 'another-secret')
    assert web._wechat_web_account()['app_id'] == 'herbal-id'
    web._wechat_clear_credentials()
    account_scope.current_persona.set('')
    assert web._wechat_web_account()['app_id'] == 'legacy-id'
    assert web._mp_login_status()['state'] == 'success'


def test_requests_choose_namespace_and_logout_cannot_delete_other_persona():
    web._write_login_marker('wechat-oa-mp', 'success')
    general = web.BROWSER_PROFILES / 'WeixinMpProfile'
    general.mkdir(parents=True)
    (general / 'cookies').write_text('general')
    api = TestClient(web.app, base_url="http://localhost:7860", headers={"Origin": "http://localhost:7860"})
    data = api.get('/api/accounts?persona=养生').json()
    assert not next(a for a in data if a['platform'] == 'wechat-oa')['loggedIn']
    assert api.post('/api/logout/wechat-oa?persona=养生').status_code == 200
    assert (general / 'cookies').read_text() == 'general'
    assert web._mp_login_status()['state'] == 'success'
    assert api.get('/api/accounts?persona=../bad').status_code == 400


def test_login_subprocess_and_qr_are_scoped(monkeypatch):
    calls = []
    def start(cmd, **kw):
        calls.append((cmd, kw['env']))
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(web.subprocess, 'Popen', start)
    api = TestClient(web.app, base_url="http://localhost:7860", headers={"Origin": "http://localhost:7860"})
    for name in ('养生', '科技'):
        assert api.post('/api/accounts/wechat-oa/mp-login', params={'persona': name}).status_code == 200
    assert [env['EASEL_ACCOUNT_PERSONA'] for _, env in calls] == ['养生', '科技']
    assert calls[0][0] != calls[1][0]
    assert len(web.LOGIN_PROCESSES) == 2
    assert not (web.LOGIN_DIR / 'wechat-oa-mp.png').exists()


def test_publish_without_persona_login_fails_before_launch(monkeypatch):
    web._write_login_marker('wechat-oa-mp', 'success')
    monkeypatch.setattr(web, '_require_automated_publishing', lambda: None)
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: pytest.fail('must not publish'))
    api = TestClient(web.app, base_url="http://localhost:7860", headers={"Origin": "http://localhost:7860"})
    response = api.post('/api/publish/wechat-oa?persona=养生', json={'persona': '养生', 'title': '稿件', 'body': '内容'})
    assert response.status_code == 400
    assert '未登录' in response.json()['detail']


def test_concurrent_checks_have_distinct_identity_and_cache(monkeypatch):
    async def check(platform, force=False):
        before = account_scope.persona()
        await asyncio.sleep(.01)
        assert account_scope.persona() == before
        return {'loggedIn': True, 'name': before, 'avatar': ''}
    monkeypatch.setattr(web, '_check_account_whoami', check)
    async def run(name):
        account_scope.current_persona.set(name)
        return await web.api_account_whoami('wechat-oa')
    async def scenario():
        return await asyncio.gather(run('养生'), run('科技'))
    assert [x['name'] for x in asyncio.run(scenario())] == ['养生', '科技']


def test_scope_overrides_legacy_profile_argument(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    account_scope.current_persona.set('养生')
    assert account_scope.browser_base('/old') == tmp_path / '.easel-browser-profiles' / 'personas' / account_scope.key()
    account_scope.current_persona.set('')
    assert account_scope.browser_base('/old') == Path('/old')


@pytest.mark.parametrize('duplicate', [False, True])
def test_transfer_preserves_history_but_never_old_runtime(tmp_path, duplicate):
    store = Conversations(tmp_path / 'history.sqlite')
    source = store.create({'id': 'shared_old', 'title': '稿件', 'created': 1, 'persona': None,
                           'sessionKey': 'old-runtime', 'messages': [
                               {'role': 'user', 'content': '草稿'}, {'role': 'assistant', 'content': '正文'}]}, importing=True)
    result = store.transfer(source['id'], 1, '养生', copy=duplicate)
    assert result['persona'] == '养生'
    assert result['messages'] == source['messages']
    assert result['agentSessionId'] != source['agentSessionId']
    assert 'sessionKey' not in result
    assert result['contextPending']
    if duplicate:
        assert store.get(source['id']) == source
    else:
        with pytest.raises(Missing): store.get(source['id'])
    started = store.begin(result['id'], 1, 'turn', {'role': 'user', 'content': '继续'}, None)
    with pytest.raises(Conflict): store.transfer(result['id'], started['revision'], '', copy=True)
    with pytest.raises(Conflict): store.transfer(result['id'], 1, '', copy=True)


def test_transfer_continuation_seeds_history_and_uses_saved_persona(monkeypatch):
    store = web._conversations()
    original = store.create({'id': 'shared_old', 'title': '草稿', 'created': 1, 'messages': [
        {'role': 'user', 'content': '历史主题'}, {'role': 'assistant', 'content': '历史正文'}]}, importing=True)
    copied = store.transfer(original['id'], 1, '养生', copy=True)
    monkeypatch.setattr(web, '_chat_backend', lambda _: 'api')
    monkeypatch.setattr(web, '_harness_settings', lambda: {})
    monkeypatch.setattr(web, '_direct_chat_content', lambda req: (req.message, 'system'))
    seen = []
    async def run(req, sk, content, system, emit):
        seen.append((req.persona, system, account_scope.persona()))
        emit('token', '续写')
    monkeypatch.setattr(web, '_run_direct_chat', run)
    async def scenario():
        await web.api_chat_stream(web.ChatRequest(conversationId=copied['id'],
            sessionId=copied['agentSessionId'], revision=1, turnId='copied-turn', message='继续', persona='科技'))
        await asyncio.gather(*list(web._BG_TASKS))
    asyncio.run(scenario())
    assert seen[0][0] == seen[0][2] == '养生'
    assert '历史正文' in seen[0][1]
    assert store.get(original['id'])['messages'] == original['messages']


def test_inherited_attachment_remains_owned_by_transferred_conversation(tmp_path):
    old_scope = web._attachment_scope('old')
    relative = f'_inbox/{old_scope}/batch/file.txt'
    full = tmp_path / relative
    full.parent.mkdir(parents=True)
    full.write_text('附件')
    attachment = {'id': web._attachment_id(old_scope, relative), 'path': relative, 'name': 'file.txt'}
    store = web._conversations()
    source = store.create({'id': 'shared_old', 'title': '附件', 'created': 1,
        'messages': [{'role': 'user', 'content': '分析', 'attachments': [attachment]},
                     {'role': 'assistant', 'content': '摘要'}]}, importing=True)
    copied = store.transfer(source['id'], 1, '养生', copy=True)
    req = web.ChatRequest(conversationId=copied['id'], sessionId=copied['agentSessionId'], message='重试', attachments=[attachment])
    assert relative in web._attachment_context(req)
    with pytest.raises(web.HTTPException):
        web._attachment_context(req.model_copy(update={'conversationId': None}))
