"""模型选择不破坏共享目录、图片路由或原来的主模型。"""
import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
import app as web


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    oc = tmp_path / 'openclaw.json'
    monkeypatch.setattr(web, '_oc_config_path', lambda: oc)
    env = tmp_path / '.env'
    env.write_text('OPENAI_BASE_URL=https://example.test/v1\nOPENAI_API_KEY=test-only\nOPENAI_MODEL=glm-5.3\n')
    monkeypatch.setattr(web, 'ENV_FILE', env)
    models = [
        {'id': 'glm-5.3', 'name': 'glm-5.3', 'input': ['text'], 'reasoning': True},
        {'id': 'glm-5.3-flash', 'name': 'glm-5.3-flash', 'input': ['text', 'image'], 'reasoning': True},
        {'id': 'deepseek-flash', 'name': 'deepseek-flash', 'input': ['text', 'image'], 'reasoning': True},
    ]
    data = {
        'models': {'providers': {'easel-openai': {
            'baseUrl': 'https://example.test/v1', 'apiKey': 'test-only',
            'agentRuntime': {'id': 'openclaw'}, 'models': models,
        }}},
        'agents': {'defaults': {
            'model': {'primary': 'easel-openai/glm-5.3', 'fallbacks': ['easel-openai/deepseek-flash']},
            'imageModel': {'primary': 'easel-openai/glm-5.3-flash', 'fallbacks': ['easel-openai/deepseek-flash']},
            'models': {f'easel-openai/{m["id"]}': {} for m in models},
        }},
    }
    data['agents']['defaults']['models']['easel-openai/glm-5.3']['alias'] = 'glm'
    oc.write_text(json.dumps(data))
    with TestClient(web.app, base_url='http://127.0.0.1:7860', client=('127.0.0.1', 51234),
                    headers={'Origin': 'http://127.0.0.1:7860'}) as client:
        yield client, oc, data


def save(client, model, primary=False):
    response = client.post('/api/settings/models/save', json={'channel': 'chat', 'rows': [
        {'slot': 'openai', 'model': model, 'primary': primary},
    ]})
    assert response.status_code == 200, response.text
    assert '失败' not in response.json().get('note', '')
    return response.json()


def test_existing_selection_only_changes_env(catalog):
    client, oc, before = catalog
    original_bytes = oc.read_bytes()
    result = save(client, 'glm-5.3-flash')
    assert oc.read_bytes() == original_bytes
    assert web._read_env()['OPENAI_MODEL'] == 'glm-5.3-flash'
    row = next(r for r in result['channels']['chat']['rows'] if r.get('slot') == 'openai')
    assert row['model'] == 'glm-5.3-flash'
    assert row['role'] == '备'
    assert not oc.with_name('openclaw.json.bak-web').exists()


def test_existing_primary_preserves_all_definitions_and_routes(catalog):
    client, oc, before = catalog
    result = save(client, 'glm-5.3-flash', primary=True)
    expected = copy.deepcopy(before)
    expected['agents']['defaults']['model']['primary'] = 'easel-openai/glm-5.3-flash'
    assert json.loads(oc.read_text()) == expected
    assert next(r for r in result['channels']['chat']['rows'] if r.get('slot') == 'openai')['role'] == '主'
    save(client, 'glm-5.3', primary=True)
    assert json.loads(oc.read_text()) == before


@pytest.mark.parametrize('primary', [False, True])
def test_new_model_is_appended_registered_and_idempotent(catalog, primary):
    client, oc, before = catalog
    save(client, 'new-model', primary)
    expected = copy.deepcopy(before)
    expected['models']['providers']['easel-openai']['models'].append({
        'id': 'new-model', 'name': 'new-model', 'input': ['text', 'image'], 'reasoning': True,
    })
    expected['agents']['defaults']['models']['easel-openai/new-model'] = {}
    if primary:
        expected['agents']['defaults']['model']['primary'] = 'easel-openai/new-model'
    assert json.loads(oc.read_text()) == expected
    save(client, 'new-model', primary)
    assert json.loads(oc.read_text()) == expected
    save(client, 'glm-5.3')
    assert json.loads(oc.read_text()) == expected


def test_missing_registration_repaired_without_overwriting_metadata(catalog):
    client, oc, before = catalog
    del before['agents']['defaults']['models']['easel-openai/glm-5.3-flash']
    before['models']['providers']['easel-openai']['models'][1]['reasoning'] = False
    oc.write_text(json.dumps(before))
    save(client, 'glm-5.3-flash')
    before['agents']['defaults']['models']['easel-openai/glm-5.3-flash'] = {}
    assert json.loads(oc.read_text()) == before


def test_custom_provider_keeps_selection_without_losing_catalog(catalog):
    client, oc, before = catalog
    provider = before['models']['providers'].pop('easel-openai')
    before['models']['providers']['myproxy'] = provider
    oc.write_text(json.dumps(before))
    original_models = copy.deepcopy(provider['models'])
    note = web._sync_openclaw_chat({'myproxy': {'model': 'glm-5.3-flash'}}, {'myproxy'}, '')
    assert '失败' not in note
    after = json.loads(oc.read_text())
    models = after['models']['providers']['myproxy']['models']
    assert models == [original_models[1], original_models[0], original_models[2]]
    assert after['agents']['defaults']['model'] == before['agents']['defaults']['model']
    assert web._sync_openclaw_chat({'myproxy': {'model': 'glm-5.3-flash'}}, {'myproxy'}, '') == ''
