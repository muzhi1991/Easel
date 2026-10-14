"""MEDIA directives removed by OpenClaw HTTP must survive in shared UI history."""
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import quote

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web


def history_message(run, text, role='assistant'):
    return {'role': role, '__openclaw': {'runId': run}, 'content': [{'type': 'text', 'text': text}]}


@pytest.mark.parametrize('unavailable', [False, True])
def test_http_media_is_persisted_without_a_browser(tmp_path, monkeypatch, unavailable):
    output = tmp_path / 'outputs'
    image = output / '卡片 with spaces' / 'card.png'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'test image')
    raw = tmp_path / 'raw.jsonl'
    raw.touch()
    monkeypatch.setattr(web, 'OUTPUTS_DIR', output)
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path / 'sessions')
    monkeypatch.setattr(web, 'DEBUG_DIR', tmp_path / 'debug')
    monkeypatch.setattr(web, 'SHARED_RAW_STREAM', raw)
    monkeypatch.setattr(web, '_chat_backend', lambda _: 'openclaw')
    monkeypatch.setattr(web, '_harness_settings', lambda: {})
    monkeypatch.setattr(web, '_heal_openclaw_session', lambda _: None)
    monkeypatch.setattr(web, '_chat_message', lambda req: req.message)
    monkeypatch.setattr(web, '_resolve_transport', lambda _: 'http')
    monkeypatch.setattr(web, '_apply_http_thinking', lambda *args: None)
    monkeypatch.setattr(web, 'question_bridge_supported', lambda: False)
    monkeypatch.setattr(web, '_QBRIDGE_DISABLED', True)
    monkeypatch.setattr(web, 'openclaw_base_cmd', lambda: ['oc'])
    class Gateway:
        def __init__(self, **kwargs): pass
        def close(self): pass
        def chat_history(self, session_key):
            assert session_key == 'agent:main:media-test'
            if unavailable:
                raise RuntimeError('history unavailable')
            return {'sessionKey': session_key, 'messages': [
                history_message('previous-run', 'MEDIA:/unrelated/file.png'),
                history_message('chatcmpl_media_test', f'成了，卡片在这儿：\nMEDIA:{image}\n说明')], 'hasMore': False}
    monkeypatch.setattr(web, 'GatewayClient', Gateway)
    class Http:
        status_code = 200
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs): return self
        async def aiter_lines(self):
            yield 'data: ' + json.dumps({'id': 'chatcmpl_media_test', 'choices': [{'delta': {'content': '成了，卡片在这儿：\n\n说明'}}]})
            await asyncio.sleep(.02)
            yield 'data: ' + json.dumps({'id': 'chatcmpl_media_test', 'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
            yield 'data: [DONE]'
    monkeypatch.setattr(httpx, 'AsyncClient', Http)
    web._conversations().create({'id': 'shared_media-test', 'title': 'test', 'created': 1, 'messages': []})
    async def run():
        await web.api_chat_stream(web.ChatRequest(
            message='card', sessionId='media-test', conversationId='shared_media-test', revision=1,
            turnId='test-turn', thinking='high'))
        # No browser consumes the returned stream. Backend completion owns persistence.
        await asyncio.gather(*list(web._BG_TASKS))
    asyncio.run(asyncio.wait_for(run(), timeout=8))
    url = '/api/media/' + quote('卡片 with spaces/card.png')
    saved = web._conversations().get('shared_media-test')['messages'][-1]['content']
    if unavailable:
        assert '附件检查未完成' in saved
        assert 'pendingTurnId' not in web._conversations().get('shared_media-test')
        assert not web._session_lock('media-test').locked()
        return
    assert f'![card.png]({url})' in saved
    assert '/unrelated/' not in saved
    assert str(tmp_path) not in saved
    latest = json.loads(web._turn_file('web:media-test').read_text())
    assert url in latest['text']
    events = [json.loads(line) for line in web._job_event_file('test-turn').read_text().splitlines()]
    tokens = ''.join(e['data'] for e in events if e['event'] == 'token')
    assert url in tokens
    assert latest['gateway_run_id'] == 'chatcmpl_media_test'


def test_directives_are_scoped_not_guessed_and_recovery_is_idempotent(tmp_path):
    from easel.chat_media import media_suffix
    root = tmp_path / 'outputs'
    root.mkdir()
    (root / 'one.png').write_bytes(b'one')
    (root / 'two.mp4').write_bytes(b'two')
    text = '\n'.join([
        'plain prose outputs/guess.png',
        '```text', 'MEDIA:outputs/example.png', '```',
        'MEDIA:outputs/one.png', f'MEDIA:"{root / "one.png"}"',
        'MEDIA:outputs/two.mp4',
    ])
    current = history_message('current', text)
    current['content'].append({'type': 'thinking', 'thinking': 'MEDIA:outputs/thought.png'})
    history = {'sessionKey': 's', 'messages': [
        history_message('previous', 'MEDIA:outputs/previous.png'),
        history_message('current', 'MEDIA:outputs/user.png', 'user'), current]}
    suffix = media_suffix(history, 's', 'current', root, 'done')
    assert suffix.count('/api/media/one.png') == 1
    assert '[two.mp4](/api/media/two.mp4)' in suffix
    assert '无法展示' not in suffix  # examples, prose, users, other runs were all ignored
    assert media_suffix(history, 's', 'current', root, 'done' + suffix) == ''


def test_missing_external_and_symlink_files_are_not_exposed(tmp_path):
    from easel.chat_media import media_suffix
    root = tmp_path / 'outputs'
    root.mkdir()
    private = tmp_path / 'private.png'
    private.write_bytes(b'private')
    (root / 'link.png').symlink_to(private)
    history = {'sessionKey': 's', 'messages': [history_message('r', '\n'.join([
        f'MEDIA:{private}', 'MEDIA:outputs/link.png', 'MEDIA:outputs/missing.png',
        'MEDIA:http://outside.example.com/file.png', 'MEDIA:outputs/../private.png',
    ]))]}
    suffix = media_suffix(history, 's', 'r', root, '')
    assert suffix.count('无法展示') == 1
    assert '/api/media/' not in suffix
    assert 'private' not in suffix


@pytest.mark.parametrize('history', [
    {'sessionKey': 'wrong', 'messages': [history_message('r', 'text')]},
    {'sessionKey': 's', 'messages': [history_message('previous', 'text')]},
    {'sessionKey': 's', 'messages': [history_message('r', 'text\n...(truncated)...')]},
])
def test_unavailable_history_never_falls_back_to_an_unrelated_turn(tmp_path, history):
    from easel.chat_media import media_suffix, MediaHistoryUnavailable
    with pytest.raises(MediaHistoryUnavailable):
        media_suffix(history, 's', 'r', tmp_path, '')


def test_history_rpc_explicitly_raises_the_default_text_cap(monkeypatch):
    from easel.gateway_questions import GatewayClient
    # Test the public request shape without connecting to a real gateway.
    client = object.__new__(GatewayClient)
    calls = []
    monkeypatch.setattr(client, '_rpc', lambda method, args: calls.append((method, args)) or {'messages': []})
    assert client.chat_history('agent:main:test') == {'messages': []}
    method, args = calls[0]
    assert method == 'chat.history'
    assert args['sessionKey'] == 'agent:main:test'
    assert args['limit'] == 10
    assert args['maxChars'] == 500000
