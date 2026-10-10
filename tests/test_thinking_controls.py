"""Reasoning defaults and transport overrides, without a real model or gateway."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web
from easel.gateway_questions import GatewayClient


def test_default_prefers_saved_config_and_rereads_changes(tmp_path, monkeypatch):
    cfg = tmp_path / 'openclaw.json'
    monkeypatch.setattr(web, '_oc_config_path', lambda: cfg)
    monkeypatch.setenv('EASEL_THINKING_LEVEL', 'low')
    assert web._thinking_default() == 'low'
    cfg.write_text(json.dumps({'agents': {'defaults': {'thinkingDefault': 'high'}}}))
    assert web._thinking_default() == 'high'
    cfg.write_text(json.dumps({'agents': {'defaults': {'thinkingDefault': 'medium'}}}))
    assert web._thinking_default() == 'medium'


def test_invalid_levels_rejected():
    for cls, payload in [(web.ChatRequest, {'message': 'hi'}), (web.ThinkingSettingsRequest, {})]:
        with pytest.raises(ValidationError):
            cls(**payload, thinking='invalid')


def test_save_targets_only_profile_thinking(tmp_path, monkeypatch):
    monkeypatch.setattr(web, '_oc_config_path', lambda: tmp_path / 'openclaw.json')
    monkeypatch.setattr(web, '_oc_state_dir', lambda: tmp_path)
    monkeypatch.setattr(web, 'openclaw_base_cmd', lambda: ['oc'])
    monkeypatch.setattr(web, '_thinking_default', lambda: 'low')
    def run(cmd, **kw):
        assert cmd == ['oc', '--profile', 'easel', 'config', 'set', 'agents.defaults.thinkingDefault', 'low']
        assert kw['env']['OPENCLAW_CONFIG_PATH'] == str(tmp_path / 'openclaw.json')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(web.subprocess, 'run', run)
    assert web.api_save_thinking_settings(web.ThinkingSettingsRequest(thinking='low')) == {'thinking': 'low'}


def test_http_patch_targets_same_session_and_closes_on_failure(monkeypatch):
    calls = []
    class Client:
        def set_thinking(self, key, level):
            calls.append((key, level))
            raise RuntimeError('unsupported level')
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(web, 'GatewayClient', Client)
    with pytest.raises(RuntimeError, match='unsupported'):
        web._apply_http_thinking('agent:main:web-test', 'xhigh')
    assert calls == [('agent:main:web-test', 'xhigh'), 'closed']


def test_rpc_uses_supported_session_patch():
    client = object.__new__(GatewayClient)
    calls = []
    client._rpc = lambda method, params: calls.append((method, params))
    client.set_thinking('agent:main:web-test', 'high')
    assert calls == [('sessions.patch', {'key': 'agent:main:web-test', 'thinkingLevel': 'high'})]


def test_nonstream_chat_passes_override(monkeypatch):
    calls = []
    monkeypatch.setattr(web, '_chat_message', lambda req: req.message)
    monkeypatch.setattr(web, 'run_agent_sync', lambda *args: calls.append(args) or 'ok')
    result = asyncio.run(web.api_chat(web.ChatRequest(message='hi', sessionId='test', thinking='low')))
    assert result == {'response': 'ok'}
    assert calls[0][-2:] == ('test', 'low')


def test_save_failure_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(web.HTTPException) as exc:
        web.api_save_thinking_settings(web.ThinkingSettingsRequest(thinking='high'))
    assert exc.value.status_code == 400


@pytest.mark.parametrize('choice,expected', [(None, 'high'), ('low', 'low')])
def test_cli_uses_resolved_level(choice, expected, tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(web, '_heal_openclaw_session', lambda sk: None)
    monkeypatch.setattr(web, '_thinking_default', lambda: 'high')
    def run(cmd, **kwargs):
        assert cmd[cmd.index('--thinking') + 1] == expected
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')
    monkeypatch.setattr(web.subprocess, 'run', run)
    assert web.run_agent_sync('hi', session_id='test', thinking=choice) == 'ok'


@pytest.mark.parametrize('choice,expected,fail', [(None, 'high', False), ('low', 'low', False), ('xhigh', 'xhigh', True)])
def test_http_turn_applies_level_before_request(choice, expected, fail, tmp_path, monkeypatch):
    import httpx
    calls = []
    monkeypatch.setattr(web, 'SESSIONS_DIR', tmp_path / 'sessions')
    monkeypatch.setattr(web, 'DEBUG_DIR', tmp_path / 'debug')
    monkeypatch.setattr(web, 'SHARED_RAW_STREAM', tmp_path / 'raw.jsonl')
    monkeypatch.setattr(web, '_heal_openclaw_session', lambda sk: None)
    monkeypatch.setattr(web, '_chat_message', lambda req: req.message)
    monkeypatch.setattr(web, '_thinking_default', lambda: 'high')
    monkeypatch.setattr(web, '_resolve_transport', lambda sk: 'http')
    monkeypatch.setattr(web, 'question_bridge_supported', lambda: False)
    monkeypatch.setattr(web, '_QBRIDGE_DISABLED', True)
    monkeypatch.setattr(web, 'openclaw_base_cmd', lambda: ['oc'])
    def patch(key, level):
        calls.append(('patch', key, level))
        if fail:
            raise RuntimeError('unsupported level')
    monkeypatch.setattr(web, '_apply_http_thinking', patch)
    class Client:
        def __init__(self, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, **kw):
            calls.append(('post', kw['headers']['x-openclaw-session-key']))
            assert calls[0] == ('patch', 'agent:main:thinking-test', expected)
            return self
        status_code = 200
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
            await asyncio.sleep(0.01)  # next network chunk
            yield 'data: [DONE]'
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    async def run():
        response = await web.api_chat_stream(web.ChatRequest(message='hi', sessionId='thinking-test', thinking=choice))
        return [item async for item in response.body_iterator]
    events = asyncio.run(asyncio.wait_for(run(), timeout=8))
    assert calls[0] == ('patch', 'agent:main:thinking-test', expected)
    if fail:
        assert len(calls) == 1
        assert any(e['event'] == 'error' and 'unsupported level' in e['data'] for e in events)
    else:
        assert calls[1] == ('post', 'agent:main:thinking-test')
        assert any(e['event'] == 'token' and 'ok' in e['data'] for e in events)
