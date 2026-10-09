"""The Codex harness requires profile-local official provenance, not a load path."""
import json
from types import SimpleNamespace
from easel import codex_backend as cb


def test_installs_official_plugin_in_selected_profile_before_model_switch(tmp_path, monkeypatch):
    cfg = tmp_path / 'openclaw.json'
    cfg.write_text(json.dumps({'agents': {'defaults': {'model': {'primary': 'other/glm'}}}}))
    monkeypatch.setattr(cb, 'config_path', lambda: cfg)
    monkeypatch.setattr(cb, 'openclaw_base_cmd', lambda: ['openclaw'])
    installed = False
    calls = []
    def inspect(plugin, **kwargs):
        return {'trustedOfficialInstall': installed, 'rootDir': str(tmp_path / 'plugin')}
    def run(argv, **kwargs):
        nonlocal installed
        assert json.loads(cfg.read_text())['agents']['defaults']['model']['primary'] == 'other/glm'
        assert kwargs['env']['OPENCLAW_STATE_DIR'] == str(tmp_path)
        assert kwargs['env']['OPENCLAW_CONFIG_PATH'] == str(cfg)
        calls.append(argv)
        installed = True
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cb, '_inspect', inspect)
    monkeypatch.setattr(cb.subprocess, 'run', run)
    cb._ensure_plugin({'pluginVersion': '2026.9.8', 'pluginPath': '/main/codex'})
    assert calls[0] == ['openclaw', 'plugins', 'install', 'npm:@openclaw/codex@2026.9.8', '--no-enable']
    cb._ensure_plugin({'pluginVersion': '2026.9.8', 'pluginPath': '/main/codex'})
    assert len(calls) == 1


def test_shared_untracked_path_is_removed_and_registry_refreshed(tmp_path, monkeypatch):
    cfg = tmp_path / 'openclaw.json'
    cfg.write_text(json.dumps({'plugins': {'load': {'paths': ['/main/codex', '/keep/me']}}}))
    monkeypatch.setattr(cb, 'config_path', lambda: cfg)
    monkeypatch.setattr(cb, 'openclaw_base_cmd', lambda: ['openclaw'])
    monkeypatch.setattr(cb, '_validate', lambda path: None)
    trusted = False
    calls = []
    monkeypatch.setattr(cb, '_inspect', lambda *a, **kw: {'trustedOfficialInstall': trusted})
    def run(argv, **kwargs):
        nonlocal trusted
        calls.append(argv)
        assert json.loads(cfg.read_text())['plugins']['load']['paths'] == ['/keep/me']
        if 'install' in argv:
            trusted = True
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cb.subprocess, 'run', run)
    cb._ensure_plugin({'pluginVersion': '2026.9.8', 'pluginPath': '/main/codex'})
    assert calls[0] == ['openclaw', 'plugins', 'registry', '--refresh', '--json']
    assert 'install' in calls[1]


def test_api_parameters_are_scoped_away_from_native_codex():
    data = {'agents': {'defaults': {
        'params': {'maxTokens': 131072},
        'model': {'primary': 'other/glm'},
        'models': {'other/glm': {'params': {'temperature': 0.2}},
                   'openai/gpt-6-astra': {'agentRuntime': {'id': 'codex'}}},
    }}, 'models': {'providers': {'other': {'models': [{'id': 'glm'}, {'id': 'flash'}]}}}}
    cb._scope_api_params(data, 'openai/gpt-6.1-sol')
    defaults = data['agents']['defaults']
    assert 'params' not in defaults
    assert defaults['models']['other/glm']['params'] == {'maxTokens': 131072, 'temperature': 0.2}
    assert defaults['models']['other/flash']['params'] == {'maxTokens': 131072}
    assert 'params' not in defaults['models']['openai/gpt-6-astra']
