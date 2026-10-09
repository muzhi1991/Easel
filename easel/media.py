"""Thin Easel seam to the independently installed media adapter package.

No model endpoints or provider-specific logic belong in this module.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def runtime():
    try:
        from easel_media_adapters import MediaRuntime
    except ImportError as exc:
        raise RuntimeError("媒体适配包未安装，请运行 .venv/bin/python -m pip install -e integrations/media-adapters") from exc
    return MediaRuntime()


def transcribe(source: Path, *, language: str = "auto", provider: str | None = None,
               model: str | None = None, max_line_chars: int = 18) -> dict:
    rt = runtime()  # Produce the installation hint before importing request types.
    from easel_media_adapters import TranscriptionRequest
    if not 1 <= max_line_chars <= 200:
        raise ValueError("max_line_chars 需介于 1 和 200")
    return rt.submit("transcribe", "transcribe",
                            TranscriptionRequest(Path(source), language, model, max_line_chars), provider)


def video_provider(provider: str | None = None) -> tuple[dict, dict]:
    instance, adapter = runtime().resolve("video", provider)
    describe = getattr(adapter, "capabilities", None)
    return instance, describe(instance) if describe else {}


def generate_video(prompt: str, output: Path, *, provider: str | None = None, **options) -> dict:
    rt = runtime()
    from easel_media_adapters import VideoRequest
    return rt.submit("video", "generate_video", VideoRequest(prompt, Path(output), **options), provider)


def write_transcript(result: dict, path: Path) -> None:
    """Never leave a partial transcript if recognition/alignment fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".transcript-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Easel 统一媒体入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("providers", help="显示适配器、实例和默认配置")
    probe = sub.add_parser("probe", help="连接探活（不代表效果验证）")
    probe.add_argument("provider")
    task = sub.add_parser("transcribe")
    task.add_argument("--src", required=True)
    task.add_argument("--out", required=True)
    task.add_argument("--lang", default="auto")
    task.add_argument("--provider")
    task.add_argument("--model")
    task.add_argument("--max-line-chars", type=int, default=18)
    args = parser.parse_args()
    try:
        if args.command == "providers":
            print(json.dumps({"adapters": runtime().describe(), **runtime().load()}, ensure_ascii=False, indent=2))
        elif args.command == "probe":
            result = runtime().probe(args.provider)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        else:
            result = transcribe(Path(args.src), language=args.lang, provider=args.provider, model=args.model,
                                max_line_chars=args.max_line_chars)
            write_transcript(result, Path(args.out))
            print(f"转写完成：{len(result['segments'])} 段，provider={result['provider']}，{args.out}")
            for note in result.get("warnings", []):
                print(f"警告：{note}")
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"媒体任务失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
