"""Versioned configuration and capability dispatch shared by all media adapters."""
from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit


class MediaError(RuntimeError):
    """Actionable failure; callers must not silently choose another backend."""


@dataclass(frozen=True)
class TranscriptionRequest:
    source: Path
    language: str = "auto"
    model: str | None = None
    max_line_chars: int = 18


@dataclass(frozen=True)
class OCRRequest:
    source: Path


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    output: Path
    voice: str | None = None
    language: str | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class MusicRequest:
    prompt: str
    output: Path
    lyrics: str | None = None
    abc: str | None = None
    cot: str | None = None
    seed: int | None = None
    instrumental: bool = False
    duration: float | None = None
    model: str | None = None
    timeout: float | None = None
    resume: bool = False
    poll_interval: float | None = None
    reference_audio: Path | None = None


@dataclass(frozen=True)
class VideoRequest:
    prompt: str
    output: Path
    first_frame: Path | None = None
    last_frame: Path | None = None
    reference_images: tuple[Path, ...] = ()
    reference_videos: tuple[Path, ...] = ()
    reference_audio: tuple[Path, ...] = ()
    duration: int = 5
    ratio: str = "16:9"
    seed: int | None = None
    model: str | None = None
    audio: str = "auto"
    timeout: float | None = None
    resume: bool = False


class Adapter(Protocol):
    descriptor: dict[str, Any]

    def probe(self, provider: dict) -> dict: ...
    def submit(self, provider: dict, capability: str, request: Any) -> dict: ...


def config_path() -> Path:
    return Path(os.environ.get("EASEL_MEDIA_CONFIG", "~/.config/easel/media-providers.json")).expanduser()


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock:
        os.chmod(path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def validate_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise MediaError("服务地址必须是无内嵌凭证、查询或 fragment 的 http(s) URL")
    try:
        url.port
    except ValueError as exc:
        raise MediaError("服务地址端口无效") from exc
    return value.rstrip("/")


class MediaRuntime:
    """Installed adapters + user instances; registration never imports web-supplied code."""

    def __init__(self, path: Path | None = None, adapters: dict | None = None):
        self.path = path or config_path()
        if adapters is None:
            from .qwen import QwenAdapter
            from .openai import OpenAITranscriptionAdapter
            from .h3 import H3Adapter
            from .rapidocr import RapidOCRAdapter
            from .speech import OpenAISpeechAdapter
            from .yue2 import YuE2Adapter
            adapters = {"qwen-asr-aligner": QwenAdapter(), "openai-transcription": OpenAITranscriptionAdapter(), "h3-video": H3Adapter(), "rapidocr": RapidOCRAdapter(), "openai-speech": OpenAISpeechAdapter(), "yue2-music": YuE2Adapter()}
            for entry in importlib.metadata.entry_points(group="easel.media_adapters"):
                if entry.name not in adapters:
                    adapters[entry.name] = entry.load()()
        self.adapters = adapters

    def describe(self) -> list[dict]:
        return [{"id": key, **adapter.descriptor} for key, adapter in self.adapters.items()]

    def load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "providers": [], "defaults": {}}
        try:
            data = json.loads(self.path.read_text())
            if data.get("schema_version") != 1:
                raise MediaError("媒体配置版本不兼容，需要迁移")
            if not isinstance(data.get("providers"), list) or not isinstance(data.get("defaults"), dict):
                raise MediaError("媒体配置结构无效")
            return data
        except (ValueError, OSError, AttributeError) as exc:
            raise MediaError(f"无法读取媒体配置 {self.path}: {exc}") from exc

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".media-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def validate(self, provider: dict) -> dict:
        pid = str(provider.get("id", ""))
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", pid):
            raise MediaError("供应商 ID 需为 1–64 位字母、数字、下划线或连字符")
        adapter = self.adapters.get(provider.get("adapter"))
        if adapter is None:
            raise MediaError("适配器未安装；请由管理员安装可信适配包")
        name = str(provider.get("name", "")).strip()
        if not name or len(name) > 100:
            raise MediaError("请输入供应商名称（最多 100 字）")
        raw = provider.get("settings", {})
        if not isinstance(raw, dict):
            raise MediaError("settings 必须是对象")
        fields = adapter.descriptor["fields"]
        if set(raw) - {f["key"] for f in fields}:
            raise MediaError("存在适配器不支持的配置字段")
        settings = {}
        for field in fields:
            key = field["key"]
            val = raw.get(key, field.get("default", ""))
            if field["type"] == "number":
                try:
                    val = float(val)
                except (TypeError, ValueError) as exc:
                    raise MediaError(f"{field['label']}必须是数字") from exc
                if not field["min"] <= val <= field["max"]:
                    raise MediaError(f"{field['label']}需介于 {field['min']} 和 {field['max']}")
            elif field["type"] == "boolean":
                if not isinstance(val, bool):
                    raise MediaError(f"{field['label']}必须是布尔值")
            else:
                val = str(val).strip()
                if field.get("required") and not val:
                    raise MediaError(f"请填写{field['label']}")
                if field["type"] == "url" and val:
                    val = validate_url(val)
                if field["type"] == "secret_ref" and val and not re.fullmatch(r"[A-Z][A-Z0-9_]*", val):
                    raise MediaError("凭证引用需是环境变量名，不能直接填写密钥")
                if field.get("choices") and val not in field["choices"]:
                    raise MediaError(f"{field['label']}不是支持的选项")
            settings[key] = val
        return {"id": pid, "name": name, "adapter": provider["adapter"], "settings": settings}

    def save_provider(self, provider: dict, default_channels: list[str] | None = None) -> dict:
        clean = self.validate(provider)
        supported = self.adapters[clean["adapter"]].descriptor["channels"]
        if any(ch not in supported for ch in (default_channels or [])):
            raise MediaError("此适配器不支持所选通道")
        with file_lock(self.path.with_suffix(".lock")):
            data = self.load()
            # Changing an adapter must not strand defaults for channels it no longer supports.
            for ch, pid in list(data["defaults"].items()):
                if pid == clean["id"] and ch not in supported:
                    del data["defaults"][ch]
            data["providers"] = [p for p in data["providers"] if p["id"] != clean["id"]] + [clean]
            for ch in default_channels or []:
                data["defaults"][ch] = clean["id"]
            self._write(data)
        return clean

    def clear_default(self, channel: str) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            data = self.load()
            data["defaults"].pop(channel, None)
            self._write(data)

    def remove_provider(self, pid: str) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            data = self.load()
            if pid in data["defaults"].values():
                raise MediaError("先将另一供应商设为默认，再删除当前默认供应商")
            data["providers"] = [p for p in data["providers"] if p["id"] != pid]
            self._write(data)

    def resolve(self, channel: str, pid: str | None = None) -> tuple[dict, Adapter]:
        data = self.load()
        pid = pid or data["defaults"].get(channel)
        if not pid:
            raise MediaError(f"未配置 {channel} 默认供应商；请在设置页添加或手动选择可选后端")
        provider = next((p for p in data["providers"] if p["id"] == pid), None)
        if provider is None:
            raise MediaError(f"供应商不存在：{pid}")
        provider = self.validate(provider)
        adapter = self.adapters[provider["adapter"]]
        if channel not in adapter.descriptor["channels"]:
            raise MediaError(f"供应商 {pid} 不支持 {channel}")
        return provider, adapter

    def probe(self, pid: str) -> dict:
        data = self.load()
        provider = next((p for p in data["providers"] if p["id"] == pid), None)
        if not provider:
            raise MediaError("供应商不存在")
        provider = self.validate(provider)
        return self.adapters[provider["adapter"]].probe(provider)

    def submit(self, channel: str, capability: str, request: Any, pid: str | None = None) -> dict:
        provider, adapter = self.resolve(channel, pid)
        if capability not in adapter.descriptor["capabilities"]:
            raise MediaError(f"此供应商不支持能力 {capability}")
        # Cross-process serialization: ASR and alignment share one GPU. Never overlap our own jobs.
        resource = getattr(adapter, "concurrency_key", lambda p: p["id"])(provider)
        lock_id = hashlib.sha256(resource.encode()).hexdigest()
        with file_lock(self.path.parent / "locks" / f"{lock_id}.lock"):
            return adapter.submit(provider, capability, request)
