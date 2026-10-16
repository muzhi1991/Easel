"""Exercise the real SSE supervisor with reordered raw diagnostics and HTTP endings."""
import asyncio
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web


@pytest.mark.parametrize('ending,expected_note,clean', [
    ('stop', None, True),
    ('done_only', None, True),
    ('tool_then_stop', None, True),
    ('user_stop', None, False),
    ('eof', '可能没写完', False),
    ('stop_without_done', '可能没写完', False),
    ('length', '被截断', False),
    ('tool_calls', '正要执行下一步', False),
    ('exception', '网关连接失败', False),
    ('error', '网关返回错误', False),
])
@pytest.mark.parametrize('raw_order', ['late_delta', 'end_last', 'no_end'])
def test_http_completion_uses_own_stream(ending, expected_note, clean, raw_order, tmp_path, monkeypatch):
    raw = tmp_path / 'raw.jsonl'
    raw.touch()
    saved = []
    consumed = threading.Event()
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path / 'sessions')
    monkeypatch.setattr(web, 'DEBUG_DIR', tmp_path / 'debug')
    monkeypatch.setattr(web, 'SHARED_RAW_STREAM', raw)
    monkeypatch.setattr(web, '_direct_api_enabled', lambda: False)
    monkeypatch.setattr(web, '_harness_settings', lambda: {'runtime': 'openclaw'})
    monkeypatch.setattr(web, '_heal_openclaw_session', lambda sk: None)
    monkeypatch.setattr(web, '_chat_message', lambda req: req.message)
    monkeypatch.setattr(web, '_resolve_transport', lambda sk: 'http')
    monkeypatch.setattr(web, '_apply_http_thinking', lambda *args: None)
    monkeypatch.setattr(web, 'question_bridge_supported', lambda: False)
    monkeypatch.setattr(web, '_QBRIDGE_DISABLED', True)
    monkeypatch.setattr(web, 'openclaw_base_cmd', lambda: ['oc'])
    monkeypatch.setattr(web, '_save_turn', lambda *args: saved.append(args))
    original = web._raw_event_for_run

    def observe(line, run_id):
        if line == 'test-drained':
            consumed.set()  # previous raw event has finished updating run_info
            return None
        return original(line, run_id)
    monkeypatch.setattr(web, '_raw_event_for_run', observe)

    class Client:
        status_code = 200
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs): return self
        async def aiter_lines(self):
            # Same run: an old delta is appended after a newer end event, exactly
            # like the captured GLM trace. This end could also be an earlier tool step.
            events = [
                {'runId': 'run-test', 'event': 'assistant_message_end', 'ts': 200},
                {'runId': 'run-test', 'event': 'assistant_thinking_stream',
                 'evtType': 'thinking_delta', 'delta': 'late diagnostic', 'ts': 100},
            ]
            if raw_order == 'end_last':
                events.reverse()
            elif raw_order == 'no_end':
                events = events[1:]
            with raw.open('a') as f:
                f.write('\n'.join(json.dumps(e) for e in events) + '\ntest-drained\n')
            assert await asyncio.to_thread(consumed.wait, 2), 'raw tail did not consume fixture'
            yield 'data: {"choices":[{"delta":{"content":"MODEL-OK"}}]}'
            await asyncio.sleep(0)  # flush the real token queue
            if ending == 'user_stop':
                web._STOPPED_CHAT.add('http-completion-' + ending)
                return
            if ending == 'tool_then_stop':
                yield 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}'
            if ending == 'exception':
                raise httpx.ReadError('connection interrupted')
            if ending == 'error':
                yield 'data: {"error":{"message":"upstream failed"}}'
                return
            if ending not in ('done_only', 'eof'):
                reason = 'stop' if ending in ('stop_without_done', 'tool_then_stop') else ending
                yield 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': reason}]})
            if ending not in ('eof', 'stop_without_done'):
                yield 'data: [DONE]'
    monkeypatch.setattr(httpx, 'AsyncClient', Client)

    async def run():
        response = await web.api_chat_stream(web.ChatRequest(
            message='test', sessionId='http-completion-' + ending, thinking='high'))
        return [item async for item in response.body_iterator]
    events = asyncio.run(asyncio.wait_for(run(), timeout=8))
    text = ''.join(json.loads(e['data']) for e in events if e['event'] in ('token', 'error'))
    assert 'MODEL-OK' in text
    if expected_note:
        assert expected_note in text
    else:
        assert '⚠️' not in text
    final = saved[-1]
    assert final[3]['clean_end'] is clean
    diag = json.loads((tmp_path / 'debug/chat-stream.jsonl').read_text().splitlines()[-1])
    assert diag['clean_end'] is clean
    assert diag['saw_message_end'] is (raw_order != 'no_end')
    assert diag['last_ev'] == ('assistant_message_end' if raw_order == 'end_last' else 'assistant_thinking_stream')
