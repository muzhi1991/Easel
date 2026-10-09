#!/usr/bin/env python3
"""Thin OCR CLI; provider protocols live in the media adapter package."""
import argparse
import os
import tempfile
from pathlib import Path

from output_paths import validate_output_path
from easel.media import recognize_text, write_transcript


def write_text(text: str, path: Path):
    fd, name = tempfile.mkstemp(prefix=".ocr-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text + "\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="图片文字识别，保存 JSON 和 TXT")
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True, help="outputs/<具体主题>/ 下的 JSON 路径")
    parser.add_argument("--provider")
    args = parser.parse_args()
    try:
        output = validate_output_path(args.out)
        if output.suffix.lower() != ".json":
            raise ValueError("--out 必须使用 .json 后缀")
        text_output = validate_output_path(output.with_suffix(".txt"))
        source = Path(args.src).expanduser().resolve()
        if source in (output, text_output):
            raise ValueError("输出不能覆盖输入图片")
        result = recognize_text(source, provider=args.provider)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_transcript(result, output)
        write_text(result["text"], text_output)
        print(f"OCR 完成：{len(result['items'])} 个文字框；{output}；{text_output}")
        for warning in result.get("warnings", []):
            print(f"提示：{warning}")
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"OCR 失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
