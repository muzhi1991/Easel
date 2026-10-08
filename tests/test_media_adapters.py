"""Exercise the public media seam: chunk offsets, real timestamps, and no fallback."""
import asyncio
import importlib.util
import json
import sys
import wave
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/media-adapters/src"))
from easel_media_adapters import MediaError, MediaRuntime, TranscriptionRequest
from easel_media_adapters.audio import chunk_ranges, segments_from_words, validate_words
from easel_media_adapters import qwen


def provider(**settings):
    return {"id": "qwen-test", "name": "内网转写", "adapter": "qwen-asr-aligner",
            "settings": {"asr_url": "http://asr.test", "aligner_url": "http://align.test", **settings}}


def runtime(tmp_path, **settings):
    rt = MediaRuntime(tmp_path / "providers.json")
    rt.save_provider(provider(**settings), ["transcribe"])
    return rt


def audio(tmp_path, duration):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1); file.setsampwidth(2); file.setframerate(16000)
        file.writeframes(b"\0\0" * round(16000 * duration))
    return path


def test_configuration_and_defaults_are_independent(tmp_path):
    rt = runtime(tmp_path)
    assert rt.load()["defaults"]["transcribe"] == "qwen-test"
    assert rt.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(MediaError, match="默认"):
        rt.remove_provider("qwen-test")
    other = provider(); other["id"] = "qwen-two"
    rt.save_provider(other, ["transcribe"])
    rt.remove_provider("qwen-test")
    assert len(rt.load()["providers"]) == 1


@pytest.mark.parametrize("settings", [
    {"chunk_seconds": 301}, {"chunk_seconds": float("nan")}, {"asr_url": "file:///tmp/file"},
    {"aligner_url": "http://user:password@host"}, {"transport": "unknown"}, {"use_proxy": "false"},
])
def test_invalid_configuration_rejected(tmp_path, settings):
    with pytest.raises(MediaError):
        runtime(tmp_path, **settings)
    assert not (tmp_path / "providers.json").exists()


def test_long_audio_chunks_have_no_gaps_and_obey_limit(tmp_path):
    path = audio(tmp_path, 371)
    ranges = chunk_ranges(path, 371, 60)
    assert ranges[0][0] == 0 and ranges[-1][1] == 371
    assert all(end - start <= 120 for start, end in ranges)
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))


def test_qwen_same_slice_and_offset_applied_once(tmp_path, monkeypatch):
    offsets, uploads = [], []
    def handle(request):
        raw = request.content
        uploads.append(raw[raw.index(b"RIFF"):raw.index(b"RIFF") + 100])
        if request.url.host == "asr.test":
            assert b"verbose_json" not in raw
            return httpx.Response(200, json={"text": "language Chinese<asr_text>你好。"})
        import re
        offset = float(re.search(rb'name="offset"\r\n\r\n([\d.]+)', raw).group(1))
        offsets.append(offset)
        return httpx.Response(200, json={"model": "forced-aligner", "words": [
            {"text": "你", "start": offset + 0.1, "end": offset + 0.5},
            {"text": "好", "start": offset + 0.5, "end": offset + 1.0},
        ]})
    monkeypatch.setattr(qwen, "client", lambda settings: httpx.Client(transport=httpx.MockTransport(handle)))
    result = runtime(tmp_path).submit("transcribe", "transcribe", TranscriptionRequest(audio(tmp_path, 130)))
    assert len(offsets) >= 2 and offsets[0] == 0 and offsets[1] > 0
    assert offsets == [chunk["start"] for chunk in result["chunks"]]
    assert all(uploads[i] == uploads[i + 1] for i in range(0, len(uploads), 2))
    assert [w["start"] for w in result["words"]][::2] == [offset + 0.1 for offset in offsets]
    assert result["segments"][1]["start"] == offsets[1] + 0.1
    assert result["segments"][0]["text"] == "你好。"
    assert result["approx_timeline"] is False
    assert result["timestamp_source"] == "forced_alignment"
    assert all(row["backend"] == "unknown" for row in result["chunks"])


def test_failure_stops_before_next_chunk_or_backend(tmp_path, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("transcriptions"):
            return httpx.Response(200, json={"text": "language Chinese<asr_text>你好"})
        return httpx.Response(503, json={"detail": "OOM"})
    monkeypatch.setattr(qwen, "client", lambda settings: httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(MediaError, match="503"):
        runtime(tmp_path).submit("transcribe", "transcribe", TranscriptionRequest(audio(tmp_path, 130)))
    assert calls == ["/v1/audio/transcriptions", "/v1/audio/alignments"]


@pytest.mark.parametrize("data, message", [
    ({"text": "language Chinese<asr_text>" + "你好" * 9000}, "异常过长"),
    ({"text": "language Chinese<asr_text>你好", "usage": {"completion_tokens": 256}}, "达到生成上限"),
])
def test_runaway_or_truncated_asr_never_sent_to_aligner(tmp_path, monkeypatch, data, message):
    calls = []
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=data)
    monkeypatch.setattr(qwen, "client", lambda settings: httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(MediaError, match=message):
        runtime(tmp_path).submit("transcribe", "transcribe", TranscriptionRequest(audio(tmp_path, 2)))
    assert calls == ["/v1/audio/transcriptions"]


def test_openai_adapter_preserves_real_words_and_refuses_text_only(tmp_path, monkeypatch):
    from easel_media_adapters import openai
    rt = MediaRuntime(tmp_path / "providers.json")
    rt.save_provider({"id": "compatible", "name": "兼容接口", "adapter": "openai-transcription",
                      "settings": {"base_url": "http://api.test/v1", "model": "asr"}}, ["transcribe"])
    data = {"text": "Hello world.", "language": "English", "words": [
        {"word": "Hello", "start": 0.1, "end": 0.5}, {"word": "world", "start": 0.5, "end": 0.9}]}
    monkeypatch.setattr(openai, "client", lambda settings: httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data))))
    result = rt.submit("transcribe", "transcribe", TranscriptionRequest(audio(tmp_path, 2)))
    assert result["words"][0]["end"] == 0.5
    data.clear(); data["text"] = "Hello world."
    with pytest.raises(MediaError, match="缺少真实时间轴"):
        rt.submit("transcribe", "transcribe", TranscriptionRequest(tmp_path / "audio.wav"))


def test_native_transport_preserves_unicode_and_file(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from easel_media_adapters.http import client
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with client({"transport": "curl"}) as http, audio(tmp_path, 1).open("rb") as file:
            result = http.post(f"http://127.0.0.1:{server.server_port}/test", data={"text": "中文\n下一句",
                               "timestamp_granularities[]": ["word", "segment"]},
                               files={"file": ("audio.wav", file, "audio/wav")})
        assert result.json()["ok"] is True
        assert "中文\n下一句".encode() in seen[0] and b"RIFF" in seen[0]
        assert seen[0].count(b'name="timestamp_granularities[]"') == 2
        assert b'\r\n\r\nword\r\n' in seen[0] and b'\r\n\r\nsegment\r\n' in seen[0]
    finally:
        server.shutdown(); server.server_close(); thread.join(5)


def test_gateway_word_request_uploads_whole_audio_and_preserves_alignment(tmp_path, monkeypatch):
    from easel_media_adapters import openai
    rt = MediaRuntime(tmp_path / "providers.json")
    rt.save_provider({"id": "gateway", "name": "组合转写", "adapter": "openai-transcription",
                      "settings": {"base_url": "http://api.test/v1", "model": "qwen3-asr-aligned",
                                   "timestamp_granularity": "word+segment", "timeout_seconds": 1900}}, ["transcribe"])
    calls = []
    payload = {"text": "Hello world.", "timestamp_source": "forced_alignment", "warnings": ["服务端诊断"],
               "words": [{"word": "Hello", "start": 0.1, "end": 0.5},
                         {"word": "world", "start": 309, "end": 309.9}]}
    def handler(request):
        calls.append(request)
        body = request.read()
        assert body.count(b'name="timestamp_granularities[]"') == 2
        assert b'\r\n\r\nword\r\n' in body and b'\r\n\r\nsegment\r\n' in body
        assert b'qwen3-asr-aligned' in body and b'RIFF' in body
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(openai, "client", lambda settings: httpx.Client(transport=httpx.MockTransport(handler)))
    result = rt.submit("transcribe", "transcribe", TranscriptionRequest(audio(tmp_path, 310)))
    assert len(calls) == 1  # Server owns chunking; the client submits the entire file once.
    assert result["duration"] == 310 and result["words"][-1]["end"] == 309.9
    assert result["timestamp_source"] == "forced_alignment"
    assert result["warnings"] == ["服务端诊断"]
    payload.pop("words")
    payload["segments"] = [{"text": "Hello world.", "start": 0, "end": 1}]
    with pytest.raises(MediaError, match="未返回 words"):
        rt.submit("transcribe", "transcribe", TranscriptionRequest(tmp_path / "audio.wav"))


def test_openai_adapter_rejects_explicit_estimated_timestamps(tmp_path, monkeypatch):
    from easel_media_adapters import openai
    rt = MediaRuntime(tmp_path / "providers.json")
    rt.save_provider({"id": "estimated", "name": "估算服务", "adapter": "openai-transcription",
                      "settings": {"base_url": "http://api.test/v1", "model": "asr"}}, ["transcribe"])
    monkeypatch.setattr(openai, "client", lambda settings: httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"approx_timeline": True}))))
    with pytest.raises(MediaError, match="估算时间轴"):
        rt.submit("transcribe", "transcribe", TranscriptionRequest(audio(tmp_path, 2)))


@pytest.mark.parametrize("words", [[], [{"text": "x", "start": 2, "end": 1}],
                                  [{"text": "x", "start": 0, "end": 100}],
                                  [{"text": "x", "start": 0, "end": float("nan")}],
                                  [{"text": "x", "start": 0, "end": 0}]])
def test_false_success_timestamps_rejected(words):
    with pytest.raises(MediaError):
        validate_words(words, 0, 10)


def test_zero_duration_units_retained_but_not_standalone_captions():
    words, notes = validate_words([{"text": "你", "start": 0.2, "end": 0.8},
                                   {"text": "好", "start": 0.8, "end": 0.8}], 0, 2)
    segments = segments_from_words(words, "你好。", 1)
    assert notes and len(segments) == 1
    assert segments[0]["text"] == "你好。"
    assert len(segments[0]["words"]) == 2


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_pipeline_existing_subtitles_precede_any_provider(tmp_path, monkeypatch):
    pipeline = load_module("media_pipeline", "skills/openclaw/video-production/vendor/video-pipeline-sdk/pipeline/run.py")
    source = tmp_path / "existing.json"; source.write_text('{"segments": []}')
    monkeypatch.setattr(pipeline, "run_cmd", lambda *a, **kw: pytest.fail("must not invoke ASR"))
    status, _ = pipeline.st_transcribe({"rd": tmp_path, "state": {"config": {"transcript": str(source)}}})
    assert status == "done"


def test_pipeline_provider_failure_does_not_run_whisper(tmp_path, monkeypatch):
    pipeline = load_module("media_pipeline_failed", "skills/openclaw/video-production/vendor/video-pipeline-sdk/pipeline/run.py")
    calls = []
    def run(argv, **kwargs):
        calls.append(argv); return 1, "service busy"
    monkeypatch.setattr(pipeline, "run_cmd", run)
    status, note = pipeline.st_transcribe({"rd": tmp_path, "state": {"source": "movie.mp4"}})
    assert status == "error" and "不自动回退" in note
    assert len(calls) == 1 and calls[0][1:4] == ["-m", "easel.media", "transcribe"]


def test_asr_json_preserves_word_timestamps(monkeypatch):
    asr = load_module("media_asr", "skills/shared/scripts/asr.py")
    result = {"timestamp_source": "forced_alignment", "segments": [
        {"start": 1, "end": 2, "text": "你好", "words": [{"word": "你", "start": 1, "end": 1.4}]}]}
    saved = json.loads(asr._render_json([(1, 2, "你好")], result))
    assert saved["segments"][0]["words"][0]["end"] == 1.4


def test_web_generic_registration_and_probe(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "web"))
    import app as web
    monkeypatch.setenv("EASEL_MEDIA_CONFIG", str(tmp_path / "providers.json"))
    payload = web.MediaProviderSaveRequest(provider=provider(), defaultChannels=["transcribe"])
    data = asyncio.run(web.api_media_save(payload))
    assert data["defaults"]["transcribe"] == "qwen-test"
    assert any(a["id"] == "qwen-asr-aligner" for a in data["adapters"])
    assert "api_key" not in data["providers"][0]["settings"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException, match="先将另一"):
        asyncio.run(web.api_media_delete("qwen-test"))
