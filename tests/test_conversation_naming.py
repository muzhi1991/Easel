"""Naming is explicit, turn-bound, and automatic results never override a user."""
import asyncio
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from easel.conversations import Conversations, Conflict
from easel.conversation_naming import parse_suggestion

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path / 'sessions')
    monkeypatch.setattr(web, '_NAMING_TURNS', {})
    monkeypatch.setattr(web, '_chat_backend', lambda _: 'api')
    monkeypatch.setattr(web, '_harness_settings', lambda: {})
    monkeypatch.setattr(web, '_direct_chat_content', lambda req: (req.message, 'system'))
    with TestClient(web.app, base_url='http://localhost:7860', headers={'Origin': 'http://localhost:7860'}) as api:
        api.post('/api/conversations', json={'id': 'shared_name', 'title': '临时标题', 'created': 1})
        yield api


def test_manual_lock_survives_auto_finish_and_next_turn(tmp_path):
    store = Conversations(tmp_path / 'db')
    store.create({'id': 'shared_a', 'title': 'New Chat', 'created': 1, 'messages': []})
    store.begin('shared_a', 1, 'one', {'role': 'user', 'content': '写文章'}, '临时')
    first = store.finish('shared_a', 'one', {'role': 'assistant', 'content': '全文'}, artifact_title='文章标题')
    assert first['title'] == '文章标题' and first['titleLocked'] is False
    running = store.begin('shared_a', first['revision'], 'two', {'role': 'user', 'content': '修改'}, '旧临时标题')
    assert running['title'] == '文章标题'
    manual = store.patch('shared_a', running['revision'], {'title': '我的名称'})
    with pytest.raises(Conflict):
        store.rename_turn('shared_a', 'two', '较早模型的命名', expected_title='文章标题')
    final = store.finish('shared_a', 'two', {'role': 'assistant', 'content': '新全文'}, artifact_title='新文章标题')
    assert final['title'] == manual['title'] and final['titleLocked'] is True
    assert final['messages'][-1]['artifactTitle'] == '新文章标题'
    next_turn = store.begin('shared_a', final['revision'], 'three', {'role': 'user', 'content': '继续'}, '过时名称')
    assert next_turn['title'] == '我的名称'
    with pytest.raises(Conflict):
        store.rename_turn('shared_a', 'two', '过时模型的命名')


@pytest.mark.parametrize('clean,manual', [(True, False), (False, False), (True, True)])
def test_supervisor_applies_only_completed_artifact_and_cleans_capability(client, monkeypatch, clean, manual):
    async def run(req, sk, content, system, emit):
        token = next(iter(web._NAMING_TURNS))
        web._name_current_turn(token, web.NamingRequest(title='成果标题', mode='artifact'))
        if manual:
            web._name_current_turn(token, web.NamingRequest(title='指定名称', mode='manual'))
        emit('token', '完整文章' if clean else '部分输出')
        web._save_turn(f'web:{sk}', 'done', '正文', {'turn_id': req.turnId, 'clean_end': clean})
    monkeypatch.setattr(web, '_run_direct_chat', run)
    response = client.post('/api/chat/stream', json={'conversationId': 'shared_name', 'sessionId': 'name',
        'revision': 1, 'turnId': 'turn', 'message': '写文章'})
    assert response.status_code == 200
    saved = web._conversations().get('shared_name')
    assert saved['title'] == ('指定名称' if manual else '成果标题' if clean else '临时标题')
    assert ('artifactTitle' in saved['messages'][-1]) == clean
    assert not web._NAMING_TURNS


def test_capability_endpoint_is_current_turn_only_and_manual_locks(client):
    store = web._conversations()
    store.begin('shared_name', 1, 'turn', {'role': 'user', 'content': '改名'}, '')
    web._NAMING_TURNS['secret'] = {'id': 'shared_name', 'turn': 'turn'}
    url = '/api/conversation-naming/current'
    body = {'title': '我的标题', 'mode': 'manual'}
    assert client.post(url, json=body).status_code == 409
    response = client.post(url, json=body, headers={'Authorization': 'Bearer secret'})
    assert response.json() == {'title': '我的标题', 'titleLocked': True}
    store.finish('shared_name', 'turn', {'role': 'assistant', 'content': '完成'})
    assert client.post(url, json=body, headers={'Authorization': 'Bearer secret'}).status_code == 409


def test_suggestion_is_read_only_reuses_exact_title_and_respects_message_selection(client, monkeypatch):
    store = web._conversations()
    store.begin('shared_name', 1, 'turn', {'role': 'user', 'content': '问题'}, '')
    original = store.finish('shared_name', 'turn', {'role': 'assistant', 'content': '成果'}, artifact_title='原始正式标题')
    def forbidden(*args, **kwargs):
        raise AssertionError('Known title must not call model')
    monkeypatch.setattr(web, 'stream_chat', forbidden)
    assert client.post('/api/conversations/shared_name/suggest-title', json={'messageIndex': 1}).json() == {'title': '原始正式标题'}
    assert store.get('shared_name') == original
    assert client.post('/api/conversations/shared_name/suggest-title', json={'messageIndex': 0}).status_code == 422
    assert client.post('/api/conversations/shared_name/suggest-title', json={'messageIndex': 1, 'historyEpoch': 3}).status_code == 409


def test_suggestion_uses_configured_model_low_without_saving(client, monkeypatch):
    store = web._conversations()
    store.begin('shared_name', 1, 'turn', {'role': 'user', 'content': '写朋友圈'}, '')
    before = store.finish('shared_name', 'turn', {'role': 'assistant', 'content': '露营文案'})
    async def model(settings, prompt, **kwargs):
        assert kwargs['thinking'] == 'low'
        assert '露营文案' in prompt
        yield 'token', '{"title":"周末露营朋友圈文案"}'
    monkeypatch.setattr(web, 'stream_chat', model)
    assert client.post('/api/conversations/shared_name/suggest-title', json={}).json()['title'] == '周末露营朋友圈文案'
    assert store.get('shared_name') == before


def test_legacy_titles_are_preserved(tmp_path):
    store = Conversations(tmp_path / 'db')
    store.create({'id': 'old', 'title': '历史自定义名称', 'created': 1, 'messages': []}, importing=True)
    store.begin('old', 1, 'turn', {'role': 'user', 'content': '写'}, '临时')
    assert store.finish('old', 'turn', {'role': 'assistant', 'content': '文'}, artifact_title='新标题')['title'] == '历史自定义名称'
    with pytest.raises(ValueError):
        parse_suggestion('{"title":" "}')
