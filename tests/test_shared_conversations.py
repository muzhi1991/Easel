"""Shared history is durable without a browser and does not overwrite stale clients."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from easel.conversations import Conversations, Conflict, Missing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web


@pytest.fixture
def store(tmp_path):
    return Conversations(tmp_path / 'conversations.sqlite')


def conversation(identifier='shared_old', **extra):
    return {'id': identifier, 'title': '历史', 'created': 1, 'messages': [], **extra}


def test_import_is_idempotent_preserves_agent_identity_and_tombstone(store):
    data = conversation(messages=[{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'hello'}],
                        persona='画像', thinking='high', archived=True)
    first = store.create(data, importing=True)
    assert first['agentSessionId'] == 'old'
    assert first['messages'] == data['messages']
    edited = store.patch(first['id'], first['revision'], {'title': '新标题'})
    assert store.create(data, importing=True) == edited
    store.delete(edited['id'], edited['revision'])
    assert store.create(data, importing=True) is None
    assert store.list() == []
    with pytest.raises(Missing):
        store.get(first['id'])


def test_stale_metadata_and_concurrent_turns_never_replace_newer_history(store):
    first = store.create(conversation())
    def send(turn):
        try:
            return store.begin(first['id'], 1, turn, {'role': 'user', 'content': turn}, 'title')
        except Conflict:
            return None
    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(send, ['one', 'two']))
    assert sum(r is not None for r in results) == 1
    running = store.get(first['id'])
    with pytest.raises(Conflict):
        store.patch(first['id'], 1, {'title': 'stale'})
    with pytest.raises(Conflict):
        store.delete(first['id'], running['revision'])
    final = store.finish(first['id'], running['pendingTurnId'], {'role': 'assistant', 'content': 'answer'})
    assert len(final['messages']) == 2
    assert store.finish(first['id'], running['pendingTurnId'], {'role': 'assistant', 'content': 'duplicate'}) == final
    with pytest.raises(Conflict):
        store.begin(first['id'], final['revision'], running['pendingTurnId'], {'role': 'user', 'content': 'duplicate'}, '')


def test_edit_retry_truncates_only_at_matching_version_and_user_message(store):
    original = store.create(conversation(messages=[{'role': 'user', 'content': 'old'},
                                                 {'role': 'assistant', 'content': 'old reply'}]), importing=True)
    with pytest.raises(Conflict):
        store.begin(original['id'], 1, 'bad', {'role': 'user', 'content': 'new'}, '', 1)
    retried = store.begin(original['id'], 1, 'retry', {'role': 'user', 'content': 'new'}, '', 0)
    assert retried['messages'] == [{'role': 'user', 'content': 'new'}]
    with pytest.raises(Conflict):
        store.patch(original['id'], retried['revision'], {'persona': 'other'})


def test_restart_recovers_partial_output_once(store, tmp_path):
    store.create(conversation())
    store.begin('shared_old', 1, 'partial', {'role': 'user', 'content': 'question'}, '')
    jobs = tmp_path / 'jobs'
    jobs.mkdir()
    (jobs / 'partial.jsonl').write_text(json.dumps({'event': 'token', 'data': 'partial output'}) + '\n{broken')
    store.recover(jobs)
    store.recover(jobs)
    recovered = store.get('shared_old')
    assert 'pendingTurnId' not in recovered
    assert len(recovered['messages']) == 2
    assert recovered['messages'][-1]['content'].startswith('partial output')
    assert '服务重启' in recovered['messages'][-1]['content']


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path / 'sessions')
    return TestClient(web.app, base_url="http://localhost:7860", headers={"Origin": "http://localhost:7860"})


def test_separate_clients_share_create_metadata_import_and_delete(api):
    other = TestClient(web.app, base_url="http://localhost:7860", headers={"Origin": "http://localhost:7860"})
    first = api.post('/api/conversations', json=conversation()).json()
    assert other.get('/api/conversations').json() == [first]
    edited = other.patch('/api/conversations/shared_old', json={'revision': 1, 'thinking': 'medium'}).json()
    assert edited['thinking'] == 'medium'
    assert api.patch('/api/conversations/shared_old', json={'revision': 1, 'title': 'stale'}).status_code == 409
    assert api.delete('/api/conversations/shared_old?revision=2').status_code == 200
    assert other.post('/api/conversations/import', json=[conversation()]).json() == [None]
    assert other.get('/api/conversations').json() == []


def test_supervisor_saves_without_consuming_browser_stream(api, monkeypatch):
    api.post('/api/conversations', json=conversation(persona='saved persona', thinking='medium'))
    monkeypatch.setattr(web, '_chat_backend', lambda _: 'api')
    monkeypatch.setattr(web, '_harness_settings', lambda: {})
    monkeypatch.setattr(web, '_direct_chat_content', lambda req: (req.message, 'system'))
    seen = []
    async def run(req, sk, content, system, emit):
        # The user's message must be committed before execution starts.
        saved = web._conversations().get('shared_old')
        seen.append((saved['messages'], req.persona, req.thinking, sk))
        await asyncio.sleep(.01)
        emit('thinking', 'analysis')
        emit('activity', 'working')
        emit('token', 'durable answer')
    monkeypatch.setattr(web, '_run_direct_chat', run)
    async def scenario():
        await web.api_chat_stream(web.ChatRequest(
            conversationId='shared_old', sessionId='old', revision=1, turnId='disconnected',
            message='agent text', displayMessage='visible text', persona='ignored', thinking='off'))
        # Deliberately never iterate the response: no browser is connected.
        await asyncio.gather(*list(web._BG_TASKS))
    asyncio.run(scenario())
    saved = api.get('/api/conversations/shared_old').json()
    assert seen == [([{'role': 'user', 'content': 'visible text', 'agentContent': 'agent text'}],
                     'saved persona', 'medium', 'old')]
    assert saved['messages'][-1] == {'role': 'assistant', 'content': 'durable answer',
                                     'thinking': 'analysis', 'activity': '⏳ 已收到…\nworking'}
    assert 'pendingTurnId' not in saved
    assert saved['revision'] == 3


def test_legacy_stream_never_creates_shared_history(api, monkeypatch):
    monkeypatch.setattr(web, '_chat_backend', lambda _: 'api')
    monkeypatch.setattr(web, '_harness_settings', lambda: {})
    monkeypatch.setattr(web, '_direct_chat_content', lambda req: (req.message, 'system'))
    async def run(req, sk, content, system, emit):
        emit('token', 'legacy answer')
    monkeypatch.setattr(web, '_run_direct_chat', run)
    async def scenario():
        await web.api_chat_stream(web.ChatRequest(sessionId='local_old', message='old browser'))
        await asyncio.gather(*list(web._BG_TASKS))
    asyncio.run(scenario())
    assert api.get('/api/conversations').json() == []
