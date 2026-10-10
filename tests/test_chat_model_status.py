"""Read-only model display uses resolved session routing, not stale UI selections."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
import app as web
from easel.gateway_questions import GatewayClient


@pytest.fixture()
def model_config(tmp_path, monkeypatch):
    path = tmp_path / 'openclaw.json'
    path.write_text(json.dumps({'agents': {'defaults': {'model': {'primary': 'easel-openai/glm-5.3-flash'}}}}))
    monkeypatch.setattr(web, '_oc_config_path', lambda: path)
    return path


def test_gateway_session_model_wins_over_default(model_config, monkeypatch):
    calls = []
    class Client:
        def __init__(self, timeout):
            pass
        def session_model(self, key):
            calls.append(key)
            return {'modelProvider': 'openai', 'model': 'gpt-6.1-sol'}
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(web, 'GatewayClient', Client)
    before = model_config.read_bytes()
    assert web.api_chat_model('test-session') == {
        'model': 'gpt-6.1-sol', 'modelRef': 'openai/gpt-6.1-sol', 'source': 'session'}
    assert calls == ['agent:main:test-session', 'closed']
    assert model_config.read_bytes() == before


@pytest.mark.parametrize('failed', [False, True])
def test_new_session_or_unavailable_gateway_falls_back_honestly(model_config, monkeypatch, failed):
    class Client:
        def __init__(self, timeout):
            pass
        def session_model(self, key):
            if failed:
                raise RuntimeError('offline')
            return None
        def close(self):
            pass
    monkeypatch.setattr(web, 'GatewayClient', Client)
    assert web.api_chat_model('test')['source'] == ('unavailable' if failed else 'default')
    assert web.api_chat_model('test')['model'] == 'glm-5.3-flash'


def test_agent_override_and_string_model(model_config):
    model_config.write_text(json.dumps({'agents': {'defaults': {'model': 'openai/default'},
        'entries': {'main': {'model': 'openai/override'}}}}))
    assert web.api_chat_model()['modelRef'] == 'openai/override'


def test_rpc_only_reads_and_matches_exact_session():
    client = object.__new__(GatewayClient)
    calls = []
    def rpc(method, params):
        calls.append((method, params))
        return {'sessions': [{'key': 'agent:main:test-other', 'model': 'wrong'},
                             {'key': 'agent:main:test', 'model': 'correct'}]}
    client._rpc = rpc
    assert client.session_model('agent:main:test')['model'] == 'correct'
    assert calls == [('sessions.list', {'search': 'agent:main:test', 'limit': 20})]


def test_invalid_session_id_rejected():
    with pytest.raises(web.HTTPException):
        web.api_chat_model('../another-session')
