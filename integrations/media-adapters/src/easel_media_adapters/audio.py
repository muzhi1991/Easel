"""Audio preparation and real word-timestamp aggregation, independent of Easel."""
from __future__ import annotations

import math
import re
import subprocess
import wave
from pathlib import Path

from .core import MediaError


def prepare(source: Path, target: Path) -> float:
    if not source.is_file():
        raise MediaError(f"音频/视频不存在：{source}")
    try:
        proc = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source),
                               "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"音频转换失败（需要 FFmpeg）：{exc}") from exc
    if proc.returncode:
        raise MediaError(f"音频转换失败：{proc.stderr[-800:]}")
    with wave.open(str(target)) as audio:
        duration = audio.getnframes() / audio.getframerate()
    if duration <= 0:
        raise MediaError("音轨为空")
    return duration


def chunk_ranges(path: Path, duration: float, target: float) -> list[tuple[float, float]]:
    """No overlap/gaps; prefer a pause around the target, always below 120 seconds."""
    pauses = []
    if duration > target:
        try:
            proc = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-af",
                                   "silencedetect=noise=-35dB:d=0.35", "-f", "null", "-"],
                                  capture_output=True, text=True, timeout=600)
            starts = re.findall(r"silence_start: ([\d.]+)", proc.stderr)
            ends = re.findall(r"silence_end: ([\d.]+)", proc.stderr)
            pauses = [(float(a) + float(b)) / 2 for a, b in zip(starts, ends)]
        except (OSError, subprocess.TimeoutExpired):
            pass  # Pause detection is optional; bounded contiguous slicing still works.
    ranges, start = [], 0.0
    while duration - start > target + 10:
        desired = start + target
        candidates = [t for t in pauses if max(start + 10, desired - 10) <= t <= min(desired + 10, start + 120)]
        end = min(candidates, key=lambda t: abs(t - desired)) if candidates else desired
        # Quantize to sample boundaries so offsets match the actual slice exactly.
        end = round(end * 16000) / 16000
        ranges.append((start, end))
        start = end
    ranges.append((start, duration))
    return ranges


def write_chunk(source: Path, dest: Path, start: float, end: float) -> None:
    with wave.open(str(source)) as audio:
        audio.setpos(round(start * audio.getframerate()))
        frames = audio.readframes(round(end * audio.getframerate()) - round(start * audio.getframerate()))
        with wave.open(str(dest), "wb") as out:
            out.setparams(audio.getparams())
            out.writeframes(frames)


def validate_words(raw: list, start: float, end: float) -> tuple[list[dict], list[str]]:
    if not isinstance(raw, list) or not raw:
        raise MediaError("对齐结果缺少 words，拒绝生成估算时间轴")
    words, previous, zero = [], start, 0
    for item in raw:
        try:
            if not isinstance(item, dict):
                raise ValueError("word must be an object")
            a, b = float(item["start"]), float(item["end"])
            body = item.get("text", item.get("word", ""))
            if not isinstance(body, str):
                raise ValueError("word text must be a string")
            body = body.strip()
        except (TypeError, KeyError, ValueError) as exc:
            raise MediaError("对齐时间戳格式无效") from exc
        if not body or not math.isfinite(a) or not math.isfinite(b) or a < start - 0.1 or b > end + 0.15 or b < a or a < previous - 0.02:
            raise MediaError("对齐结果存在越界、倒序或无效时间戳")
        a, b = max(start, min(a, end)), max(start, min(b, end))
        zero += int(a == b)
        words.append({"word": body, "start": round(a, 3), "end": round(b, 3)})
        previous = b
    if all(w["start"] == w["end"] for w in words):
        raise MediaError("对齐结果全为零时长，拒绝作为成功字幕")
    warnings = [f"{zero}/{len(words)} 个对齐单位为零时长，字幕已按真实时间合并"] if zero else []
    return words, warnings


def segments_from_words(words: list[dict], text: str, max_chars: int) -> list[dict]:
    """Keep punctuation from ASR where possible; never estimate timestamps by text length."""
    segments, group, bodies, cursor = [], [], [], 0
    cjk = bool(re.search(r"[\u3400-\u9fff]", text))
    for i, word in enumerate(words):
        token = word["word"].strip()
        pos = text.find(token, cursor)
        if pos >= 0:
            stop = pos + len(token)
            while stop < len(text) and (text[stop].isspace() or text[stop] in "，。！？；、：,.!?;:…\"'”’）)"):
                stop += 1
            body = text[pos:stop]
            cursor = stop
        else:
            body = token + ("" if cjk else " ")
        group.append(word)
        bodies.append(body)
        caption = "".join(bodies).strip()
        should_flush = (len(caption) >= max_chars or bool(re.search(r"[。！？.!?]$", caption)) or i == len(words) - 1)
        if should_flush and group[-1]["end"] > group[0]["start"]:
            segments.append({"start": group[0]["start"], "end": group[-1]["end"], "text": caption, "words": group})
            group, bodies = [], []
    if group:
        if not segments:
            raise MediaError("无法从对齐结果生成有效字幕")
        segments[-1]["words"].extend(group)
        segments[-1]["text"] += ("" if cjk else " ") + "".join(bodies).strip()
        segments[-1]["end"] = max(segments[-1]["end"], group[-1]["end"])
    return segments
