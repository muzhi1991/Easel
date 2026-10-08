"""llama.cpp Qwen ASR + Qwen ForcedAligner, with bounded sequential chunks."""
from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import httpx

from .audio import chunk_ranges, prepare, segments_from_words, validate_words, write_chunk
from .core import MediaError, TranscriptionRequest
from .http import client, json_response

LANGUAGES = {"zh": "Chinese", "en": "English", "yue": "Cantonese", "ja": "Japanese",
             "ko": "Korean", "de": "German", "fr": "French", "es": "Spanish", "ru": "Russian",
             "it": "Italian", "pt": "Portuguese"}


class QwenAdapter:
    descriptor = {
        "name": "Qwen ASR + Forced Aligner", "channels": ["transcribe"],
        "capabilities": ["transcribe"], "interface_version": 1,
        "limits": {"max_chunk_seconds": 120, "languages": list(LANGUAGES), "diarization": False},
        "fields": [
            {"key": "asr_url", "label": "ASR 根地址（不含 /v1）", "type": "url", "required": True},
            {"key": "aligner_url", "label": "对齐根地址（不含 /v1）", "type": "url", "required": True},
            {"key": "model", "label": "ASR 模型", "type": "text", "default": "qwen3-asr", "required": True},
            {"key": "chunk_seconds", "label": "切片目标秒数", "type": "number", "default": 30, "min": 20, "max": 110},
            {"key": "timeout_seconds", "label": "单请求超时秒数", "type": "number", "default": 180, "min": 10, "max": 7200},
            {"key": "use_proxy", "label": "使用环境代理（内网通常关闭）", "type": "boolean", "default": False},
            {"key": "transport", "label": "HTTP 传输", "type": "text", "default": "httpx", "choices": ["httpx", "curl"]},
        ],
    }

    def concurrency_key(self, provider: dict) -> str:
        # Multiple names for the same GPU endpoint still share one cross-process lock.
        return "qwen:" + provider["settings"]["asr_url"]

    def probe(self, provider: dict) -> dict:
        settings = provider["settings"]
        checks = []
        try:
            with client(settings) as http:
                for key in ("asr_url", "aligner_url"):
                    data = json_response(http.get(settings[key] + "/health"))
                    ok = data.get("status") == "ok" or data.get("ok") is True
                    checks.append({"endpoint": key, "ok": ok, "busy": bool(data.get("busy")),
                                   "max_audio_seconds": data.get("max_audio_seconds")})
            return {"ok": all(c["ok"] for c in checks), "checks": checks,
                    "detail": "仅连接探活；识别与对齐质量需真实音频验证"}
        except (httpx.HTTPError, MediaError) as exc:
            return {"ok": False, "checks": checks, "detail": str(exc)}

    def submit(self, provider: dict, capability: str, request: TranscriptionRequest) -> dict:
        if capability != "transcribe" or not isinstance(request, TranscriptionRequest):
            raise MediaError("Qwen 适配器需要 TranscriptionRequest")
        started = time.monotonic()
        settings = provider["settings"]
        segments, words, warnings, chunks, texts, languages = [], [], [], [], [], []
        try:
            with tempfile.TemporaryDirectory(prefix="easel-qwen-") as tmp, client(settings) as http:
                normalized = Path(tmp) / "audio.wav"
                duration = prepare(request.source, normalized)
                for index, (start, end) in enumerate(chunk_ranges(normalized, duration, settings["chunk_seconds"])):
                    audio = Path(tmp) / "chunk.wav"
                    write_chunk(normalized, audio, start, end)
                    # This deployed llama.cpp endpoint explicitly parses these form fields.
                    # Bound generation so repetitive audio cannot run away to 30k+ characters.
                    token_limit = max(256, int((end - start) * 24))
                    fields = {"model": request.model or settings["model"], "response_format": "json",
                              "temperature": "0", "max_tokens": str(token_limit)}
                    if request.language != "auto":
                        fields["language"] = LANGUAGES.get(request.language.lower(), request.language)
                    with audio.open("rb") as file:
                        asr = json_response(http.post(settings["asr_url"] + "/v1/audio/transcriptions",
                                                     data=fields, files={"file": ("chunk.wav", file, "audio/wav")}))
                    raw = str(asr.get("text", "")).strip()
                    match = re.match(r"\s*language\s*:?\s*([^<]*?)\s*<asr_text>", raw, re.I)
                    detected = match.group(1).strip() if match else str(asr.get("language", ""))
                    body = re.sub(r"<[^>]+>", "", raw[match.end():] if match else raw).strip()
                    if not body:
                        chunks.append({"index": index, "start": start, "end": end, "status": "no_speech"})
                        continue
                    if len(body) > 16000 or len(re.sub(r"\s", "", body)) > (end - start) * 50 + 100:
                        raise MediaError(f"切片 {index + 1} ASR 文本异常过长（{len(body)} 字符），疑似重复生成；请缩短切片并检查 ASR")
                    usage = asr.get("usage") or {}
                    if usage.get("completion_tokens", 0) >= token_limit:
                        raise MediaError(f"切片 {index + 1} ASR 达到生成上限，可能被截断；请缩短切片，拒绝作为完整转写")
                    lang = request.language if request.language != "auto" else detected
                    align_lang = LANGUAGES.get(lang.lower(), next((v for v in LANGUAGES.values() if v.lower() == lang.lower()), ""))
                    if not align_lang:
                        raise MediaError("无法确定对齐语言，请显式选择 zh/en 等支持的语言")
                    with audio.open("rb") as file:
                        aligned = json_response(http.post(settings["aligner_url"] + "/v1/audio/alignments",
                                                         data={"text": body, "language": align_lang, "offset": str(start)},
                                                         files={"file": ("chunk.wav", file, "audio/wav")}))
                    # The service already adds offset. Never add it a second time.
                    chunk_words, notes = validate_words(aligned.get("words"), start, end)
                    segments.extend(segments_from_words(chunk_words, body, request.max_line_chars))
                    words.extend(chunk_words)
                    texts.append(body)
                    languages.append(align_lang)
                    warnings.extend(f"切片 {index + 1}: {note}" for note in notes)
                    chunks.append({"index": index, "start": start, "end": end, "status": "succeeded",
                                   "asr_model": request.model or settings["model"], "aligner_model": aligned.get("model"),
                                   "backend": asr.get("backend", "unknown"), "word_count": len(chunk_words)})
        except httpx.HTTPError as exc:
            raise MediaError(f"Qwen 请求失败：{exc}；不自动回退或重交") from exc
        if not words:
            raise MediaError("整段音频没有识别到语音，不生成空的成功字幕")
        return {"state": "succeeded", "provider": provider["id"], "adapter": "qwen-asr-aligner",
                "model": request.model or settings["model"], "language": languages[0],
                "duration": duration, "duration_sec": duration, "source": str(request.source),
                "text": "\n".join(texts), "segments": segments, "words": words,
                "approx_timeline": False, "timestamp_source": "forced_alignment",
                "warnings": warnings, "chunks": chunks, "elapsed_seconds": round(time.monotonic() - started, 3)}
