from tests import test_web_anthropic_slot as existing
web = existing.web
sandbox = existing.sandbox


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

