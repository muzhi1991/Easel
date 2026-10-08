"""Second adapter at the same seam: OpenAI-style timestamped transcription."""
import tempfile
from pathlib import Path

import httpx

from .audio import prepare, segments_from_words, validate_words
from .core import MediaError, TranscriptionRequest
from .http import client, json_response


class OpenAITranscriptionAdapter:
    descriptor = {
        "name": "OpenAI 兼容转写（需真实时间戳）", "channels": ["transcribe"],
        "capabilities": ["transcribe"], "interface_version": 1,
        "fields": [
            {"key": "base_url", "label": "API 根地址（通常含 /v1）", "type": "url", "required": True},
            {"key": "model", "label": "模型", "type": "text", "required": True},
            {"key": "api_key_env", "label": "凭证环境变量名（无鉴权可留空）", "type": "secret_ref"},
            {"key": "timeout_seconds", "label": "超时秒数", "type": "number", "default": 600, "min": 10, "max": 7200},
            {"key": "use_proxy", "label": "使用环境代理", "type": "boolean", "default": False},
            {"key": "transport", "label": "HTTP 传输", "type": "text", "default": "httpx", "choices": ["httpx", "curl"]},
        ],
    }

    def probe(self, provider):
        try:
            with client(provider["settings"]) as http:
                json_response(http.get(provider["settings"]["base_url"] + "/models"))
            return {"ok": True, "detail": "仅连接/鉴权探测；未验证音频或时间戳"}
        except (httpx.HTTPError, MediaError) as exc:
            return {"ok": False, "detail": str(exc)}

    def submit(self, provider, capability, request):
        if capability != "transcribe" or not isinstance(request, TranscriptionRequest):
            raise MediaError("需要 TranscriptionRequest")
        settings = provider["settings"]
        try:
            with tempfile.TemporaryDirectory(prefix="easel-asr-") as tmp, client(settings) as http:
                audio = Path(tmp) / "audio.wav"
                duration = prepare(request.source, audio)
                fields = {"model": request.model or settings["model"], "response_format": "verbose_json"}
                if request.language != "auto":
                    fields["language"] = request.language
                with audio.open("rb") as file:
                    data = json_response(http.post(settings["base_url"] + "/audio/transcriptions", data=fields,
                                                   files={"file": ("audio.wav", file, "audio/wav")}))
        except httpx.HTTPError as exc:
            raise MediaError(f"转写请求失败：{exc}") from exc
        raw_words = data.get("words") or [w for s in data.get("segments", []) for w in s.get("words", [])]
        if raw_words:
            words, warnings = validate_words(raw_words, 0, duration)
            segments = segments_from_words(words, data.get("text", ""), request.max_line_chars)
        else:
            segments, words, warnings = [], [], []
            previous = 0
            for row in data.get("segments", []):
                validated, _ = validate_words([{"text": row.get("text"), "start": row.get("start"), "end": row.get("end")}], previous, duration)
                word = validated[0]
                segments.append({"text": word["word"], "start": word["start"], "end": word["end"], "words": []})
                previous = word["end"]
            if not segments:
                raise MediaError("服务仅返回文本，缺少真实时间轴；请使用对齐适配器")
        return {"state": "succeeded", "provider": provider["id"], "adapter": "openai-transcription",
                "model": request.model or settings["model"], "language": data.get("language", request.language),
                "duration": duration, "duration_sec": duration, "source": str(request.source),
                "text": data.get("text", ""), "segments": segments, "words": words,
                "approx_timeline": False, "timestamp_source": "provider", "warnings": warnings}
