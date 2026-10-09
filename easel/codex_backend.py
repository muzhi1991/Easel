"""Codex 接入：发现本机插件，迁移旧 API 槽位，校验后一次写入专用实例。

不读取主实例的密钥，不改 .env，不调用模型。登录检查不等于推理验证。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from easel.openclaw_cmd import openclaw_base_cmd
from easel.openclaw_workspace import config_path
from easel.timeouts import TIMEOUT_LOCAL_AGENT_CONFIG

LEGACY_OPENAI_PROVIDER = "easel-openai"
DEFAULT_MODEL = "gpt-6.1-sol"
_discovery_cache: tuple[float, str, dict] | None = None


def _inspect(plugin: str, *, main: bool = False) -> dict:
    env = os.environ.copy()
    # Discovery must address the selected instance even under a profile-specific parent.
    home = Path.home() / ".openclaw" if main else config_path().parent
    env.update(OPENCLAW_STATE_DIR=str(home), OPENCLAW_CONFIG_PATH=str(home / "openclaw.json"))
    env.pop("OPENCLAW_PROFILE", None)
    try:
        result = subprocess.run(openclaw_base_cmd() + ["plugins", "info", plugin, "--json"],
                                env=env, capture_output=True, text=True,
                                timeout=TIMEOUT_LOCAL_AGENT_CONFIG)
        return json.loads(result.stdout).get("plugin", {}) if result.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def discover() -> dict:
    """Only reuse a locally registered official plugin; never install from the network."""
    global _discovery_cache
    key = str(config_path())
    if _discovery_cache and _discovery_cache[1] == key and time.monotonic() - _discovery_cache[0] < 60:
        return _discovery_cache[2]
    result: dict = {"supported": False, "models": [], "reason": "未找到本机 OpenClaw Codex 插件"}
    if not shutil.which("codex") or not shutil.which("openclaw"):
        return result
    plugin = _inspect("codex")
    if not plugin:
        plugin = _inspect("codex", main=True)
    root = Path(plugin.get("rootDir") or "/nonexistent")
    if plugin.get("id") == "codex" and plugin.get("packageName") == "@openclaw/codex" and root.is_dir():
        provider = _inspect("openai")
        manifest = Path(provider.get("rootDir") or "/nonexistent") / "openclaw.plugin.json"
        try:
            catalog = json.loads(manifest.read_text(encoding="utf-8"))["modelCatalog"]["providers"]["openai"]["models"]
            models = [{"id": m["id"], "name": m.get("name") or m["id"]}
                      for m in catalog if isinstance(m.get("id"), str) and m["id"].startswith("gpt-")]
            if models:
                result = {"supported": True, "models": models, "pluginPath": str(root), "reason": ""}
        except (OSError, ValueError, KeyError, TypeError):
            result["reason"] = "无法读取 OpenClaw 的 GPT 模型目录，请检查 OpenAI 插件"
    _discovery_cache = (time.monotonic(), key, result)
    return result


def status(data: dict) -> dict:
    defaults = data.get("agents", {}).get("defaults", {})
    model = defaults.get("model", {})
    primary = model if isinstance(model, str) else model.get("primary", "")
    routes = defaults.get("models", {})
    plugin = data.get("plugins", {}).get("entries", {}).get("codex", {})
    allow = data.get("plugins", {}).get("allow")
    plugins = data.get("plugins", {})
    configured = (plugins.get("enabled") is not False and "codex" not in plugins.get("deny", [])
                  and "openai" not in data.get("models", {}).get("providers", {})
                  and plugin.get("enabled") is True and (allow is None or "codex" in allow)) and any(
        ref.startswith("openai/") and v.get("agentRuntime", {}).get("id") == "codex"
        for ref, v in routes.items() if isinstance(v, dict))
    active = configured and primary.startswith("openai/") and routes.get(primary, {}).get("agentRuntime", {}).get("id") == "codex"
    return {"configured": configured, "active": active, "currentModel": primary.split("/", 1)[-1] if active else ""}


def openai_slot_provider(data: dict) -> str:
    """The legacy .env slot keeps its own API route after Codex claims openai/*."""
    providers = data.get("models", {}).get("providers", {})
    routes = data.get("agents", {}).get("defaults", {}).get("models", {})
    has_codex = any(v.get("agentRuntime", {}).get("id") == "codex"
                    for v in routes.values() if isinstance(v, dict))
    return LEGACY_OPENAI_PROVIDER if LEGACY_OPENAI_PROVIDER in providers or has_codex else "openai"


def _move_legacy_provider(data: dict) -> None:
    providers = data.setdefault("models", {}).setdefault("providers", {})
    if "openai" not in providers:
        return
    old = providers["openai"]
    if LEGACY_OPENAI_PROVIDER in providers and providers[LEGACY_OPENAI_PROVIDER] != old:
        raise ValueError("已有不同的 easel-openai 配置，无法自动迁移；原配置未修改")
    # Migrate only references to models explicitly supplied by this API provider.
    ids = {m["id"] for m in old.get("models", []) if isinstance(m, dict) and m.get("id")}
    refs = {f"openai/{m}": f"{LEGACY_OPENAI_PROVIDER}/{m}" for m in ids}

    def rewrite(value):
        if isinstance(value, str):
            return refs.get(value, value)
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        if isinstance(value, dict):
            if any(k in refs and refs[k] in value for k in value):
                raise ValueError("模型配置迁移存在同名冲突；原配置未修改")
            return {refs.get(k, k): rewrite(v) for k, v in value.items()}
        return value

    if "agents" in data:
        data["agents"] = rewrite(data["agents"])
    providers[LEGACY_OPENAI_PROVIDER] = providers.pop("openai")


def _check_login(command: str) -> None:
    result = subprocess.run([command, "login", "status"], capture_output=True,
                            text=True, timeout=TIMEOUT_LOCAL_AGENT_CONFIG)
    if result.returncode != 0:
        raise ValueError("Codex 尚未登录，请先在终端运行 codex login，再点击接入")


def _validate(path: Path) -> None:
    env = os.environ.copy()
    env.update(OPENCLAW_CONFIG_PATH=str(path), OPENCLAW_STATE_DIR=str(config_path().parent))
    result = subprocess.run(openclaw_base_cmd() + ["config", "validate", "--json"],
                            env=env, capture_output=True, text=True,
                            timeout=TIMEOUT_LOCAL_AGENT_CONFIG)
    # Do not return CLI stderr: it can include provider credentials.
    try:
        valid = result.returncode == 0 and json.loads(result.stdout).get("valid") is True
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("OpenClaw 拒绝 Codex 配置，未保存；请检查插件与 OpenClaw 版本兼容性")


def enable(model: str = "") -> str:
    discovery = discover()
    if not discovery["supported"]:
        raise ValueError(discovery["reason"])
    ids = [m["id"] for m in discovery["models"]]
    chosen = model or (DEFAULT_MODEL if DEFAULT_MODEL in ids else ids[0])
    if chosen not in ids:
        raise ValueError("所选模型不在本机 OpenClaw 的 GPT 可选目录中")
    command = shutil.which("codex")
    if not command:
        raise ValueError("未找到本机 Codex")
    _check_login(command)
    path = config_path()
    raw = path.read_bytes()
    data = json.loads(raw)
    _move_legacy_provider(data)
    plugins = data.setdefault("plugins", {})
    if plugins.get("enabled") is False:
        raise ValueError("OpenClaw 已全局禁用插件，请先启用插件功能")
    for plugin_id in ("codex", "openai"):
        plugins.setdefault("entries", {}).setdefault(plugin_id, {})["enabled"] = True
        if isinstance(plugins.get("allow"), list) and plugin_id not in plugins["allow"]:
            plugins["allow"].append(plugin_id)
        if plugin_id in plugins.get("deny", []):
            plugins["deny"].remove(plugin_id)
    paths = plugins.setdefault("load", {}).setdefault("paths", [])
    if discovery["pluginPath"] not in paths:
        paths.append(discovery["pluginPath"])
    config = plugins["entries"]["codex"].setdefault("config", {})
    config.setdefault("sessionCatalog", {})["enabled"] = False
    app_server = config.setdefault("appServer", {})
    if app_server.get("transport", "stdio") != "stdio":
        raise ValueError("已有远程 Codex 接入配置，不能用本机接入覆盖它")
    app_server.update(command=command, homeScope="user")
    defaults = data.setdefault("agents", {}).setdefault("defaults", {})
    # An agent-level override would otherwise make a successful save ineffective.
    for entry in data["agents"].get("list", []):
        if entry.get("id") == "main" and entry.get("model"):
            raise ValueError("main Agent 设置了独立模型，请先移除该覆盖再使用一键接入")
    ref = f"openai/{chosen}"
    defaults.setdefault("models", {}).setdefault(ref, {}).setdefault("agentRuntime", {})["id"] = "codex"
    primary = defaults.get("model", {})
    if isinstance(primary, str):
        primary = {"primary": primary}
    primary["primary"] = ref
    defaults["model"] = primary
    allow = defaults.get("modelPolicy", {}).get("allow")
    if isinstance(allow, list) and ref not in allow:
        allow.append(ref)
    if data == json.loads(raw):
        return f"Codex 已接入，当前模型 {chosen}（未执行推理测试）"
    fd, candidate = tempfile.mkstemp(prefix=".codex-config-", suffix=".json", dir=path.parent)
    temp = Path(candidate)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        _validate(temp)
        if path.read_bytes() != raw:
            raise ValueError("配置刚被其他进程修改，请刷新后重试")
        shutil.copy2(path, path.with_name(path.name + ".bak-codex"))
        os.chmod(path.with_name(path.name + ".bak-codex"), 0o600)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return f"Codex 已接入并设为主模型：{chosen}；配置与登录检查通过，未执行推理测试"
