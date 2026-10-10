from tests import test_web_anthropic_slot as existing
web = existing.web
sandbox = existing.sandbox


def test_fake_ip_requires_exact_configured_origin(monkeypatch):
    monkeypatch.setenv("EASEL_FAKE_IP_ORIGINS", "https://proxy.example.com:60443")
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *_: [(2, 1, 6, "", ("198.18.0.43", 0))])
    assert web._ssrf_safe("https://proxy.example.com:60443/v1")
    assert not web._ssrf_safe("https://other.example.com:60443/v1")
    assert not web._ssrf_safe("https://proxy.example.com:443/v1")
    monkeypatch.delenv("EASEL_FAKE_IP_ORIGINS")
    assert not web._ssrf_safe("https://proxy.example.com:60443/v1")


def test_trusted_origin_still_rejects_real_private_ip(monkeypatch):
    monkeypatch.setenv("EASEL_FAKE_IP_ORIGINS", "https://proxy.example.com:60443")
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *_: [(2, 1, 6, "", ("192.168.1.1", 0))])
    assert not web._ssrf_safe("https://proxy.example.com:60443/v1")


def test_selftest_includes_custom_provider(sandbox, monkeypatch):
    import json
    config = json.loads(sandbox.oc_file.read_text())
    config["models"]["providers"]["custom"] = {
        "baseUrl": "https://custom.example.com/v1", "apiKey": "test-key",
        "api": "openai-completions", "models": [{"id": "test-model"}],
    }
    sandbox.oc_file.write_text(json.dumps(config))
    seen = existing._capture_probes(monkeypatch)
    response = sandbox.post("/api/settings/models/selftest", json={"channel": "chat"})
    assert response.status_code == 200
    assert any(url == "https://custom.example.com/v1/models" for url, _ in seen)


def test_launcher_trusts_saved_api_provider_when_codex_is_primary(sandbox, monkeypatch, capsys):
    """Exercise the launcher's actual Python block, not a duplicated resolver."""
    import json
    from pathlib import Path
    config = json.loads(sandbox.oc_file.read_text())
    config['agents']['defaults']['model']['primary'] = 'openai/gpt-6.1-sol'
    config['models']['providers'] = {'easel-openai': {
        'baseUrl': 'https://proxy.example.com:60443/v1',
        'apiKey': 'test-key', 'models': [{'id': 'glm-5.3'}],
    }}
    sandbox.oc_file.write_text(json.dumps(config))
    monkeypatch.delenv('EASEL_OPENCLAW_STATE_DIR', raising=False)
    launcher = (Path(__file__).resolve().parents[1] / 'start-web-lan.sh').read_text()
    script = launcher.split("<<'PYCONFIG'\n", 1)[1].split('\nPYCONFIG', 1)[0]
    exec(compile(script, 'launcher-config', 'exec'), {})
    origins = capsys.readouterr().out.strip()
    assert origins == 'https://proxy.example.com:60443'
    monkeypatch.setenv('EASEL_FAKE_IP_ORIGINS', origins)
    monkeypatch.setattr(web.socket, 'getaddrinfo', lambda *_: [(2, 1, 6, '', ('198.18.0.43', 0))])
    assert web._ssrf_safe('https://proxy.example.com:60443/v1')
    assert not web._ssrf_safe('https://other.example.com:60443/v1')
    assert not web._ssrf_safe('https://proxy.example.com:443/v1')
    monkeypatch.setattr(web.socket, 'getaddrinfo', lambda *_: [(2, 1, 6, '', ('192.168.1.1', 0))])
    assert not web._ssrf_safe('https://proxy.example.com:60443/v1')
