"""RapidOCR multipart protocol, isolated from Easel and OpenClaw."""
from __future__ import annotations

import math
import warnings
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from .core import MediaError, OCRRequest

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000


class RapidOCRAdapter:
    descriptor = {
        "name": "RapidOCR", "interface_version": 1,
        "channels": ["ocr"], "capabilities": ["recognize_text"],
        "fields": [
            {"key": "base_url", "label": "Base URL（服务根地址）", "type": "url", "required": True},
            {"key": "timeout_seconds", "label": "请求超时（秒）", "type": "number", "default": 120, "min": 1, "max": 600},
            {"key": "use_proxy", "label": "使用环境代理", "type": "boolean", "default": False},
        ],
    }

    def client(self, provider):
        s = provider["settings"]
        return httpx.Client(trust_env=s["use_proxy"], follow_redirects=False,
                            timeout=httpx.Timeout(s["timeout_seconds"], connect=10))

    def concurrency_key(self, provider):
        return "rapidocr:" + provider["settings"]["base_url"]

    def probe(self, provider):
        try:
            with self.client(provider) as client:
                response = client.get(provider["settings"]["base_url"] + "/health")
                response.raise_for_status()
                data = response.json()
                ok = isinstance(data, dict) and data.get("status") == "ok"
                return {"ok": ok, "detail": "RapidOCR 连接正常（非效果验证）" if ok else "健康状态异常"}
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "detail": f"RapidOCR 探活失败：{type(exc).__name__}"}

    def submit(self, provider, capability, request: OCRRequest):
        if capability != "recognize_text":
            raise MediaError("RapidOCR 不支持此能力")
        source = Path(request.source).expanduser()
        try:
            with source.open("rb") as file:
                payload = file.read(MAX_BYTES + 1)
        except OSError as exc:
            raise MediaError("无法读取 OCR 输入图片") from exc
        if not payload or len(payload) > MAX_BYTES:
            raise MediaError("OCR 图片需为非空文件且不超过 20 MiB")
        from io import BytesIO
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(payload)) as image:
                    width, height = image.size
                    encoded_size = (width, height)
                    if width * height > MAX_PIXELS:
                        raise MediaError("OCR 图片不超过 5000 万像素")
                    if image.format not in ("PNG", "JPEG", "WEBP", "BMP", "TIFF") or getattr(image, "n_frames", 1) != 1:
                        raise MediaError("仅支持单帧 PNG/JPEG/WebP/BMP/TIFF 图片")
                    mime = Image.MIME[image.format]
                    orientation = image.getexif().get(274, 1)
                    if orientation in (5, 6, 7, 8):
                        width, height = height, width
                with Image.open(BytesIO(payload)) as image:
                    image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise MediaError("OCR 输入不是有效的安全尺寸图片") from exc
        try:
            with self.client(provider) as client:
                response = client.post(provider["settings"]["base_url"] + "/ocr",
                                       files={"image_file": ("image", payload, mime)})
                response.raise_for_status()
                raw = response.json()
        except httpx.TimeoutException as exc:
            raise MediaError("OCR 请求超时；服务可能仍在识别，未自动重试") from exc
        except httpx.HTTPStatusError as exc:
            raise MediaError(f"OCR 服务返回 HTTP {exc.response.status_code}，未自动重试") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaError("OCR 连接失败或响应不是 JSON，未自动重试") from exc
        items = self.validate_result(raw, width, height, encoded_size)
        notes = [] if items else ["未检测到文字"]
        if raw["image"] != {"width": width, "height": height}:
            notes.append("服务返回原始图片尺寸；已按 EXIF 转正校正输出尺寸，原始响应保留在 raw")
        return {"provider": provider["id"], "adapter": "rapidocr", "backend": provider["settings"]["base_url"],
                "source": str(source.resolve()), "text": raw["text"], "items": items,
                "image": {"width": width, "height": height}, "coordinate_space": "exif_transposed_pixels",
                "source_exif_orientation": orientation, "warnings": notes, "raw": raw}

    @staticmethod
    def validate_result(raw, width, height, encoded_size=None):
        def number(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str) or not isinstance(raw.get("items"), list):
            raise MediaError("OCR 响应缺少文字或文字框")
        image = raw.get("image")
        if not isinstance(image, dict) or (image.get("width"), image.get("height")) not in ((width, height), encoded_size):
            raise MediaError("OCR 响应尺寸与 EXIF 转正后的图片不一致")
        for item in raw["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise MediaError("OCR 文字项格式错误")
            score, box = item.get("score"), item.get("box")
            if not number(score) or not 0 <= score <= 1:
                raise MediaError("OCR 置信度缺失或无效")
            if not isinstance(box, list) or len(box) != 4 or any(
                not isinstance(point, list) or len(point) != 2 or not all(number(v) for v in point) for point in box
            ):
                raise MediaError("OCR 坐标需为四点多边形，不能伪造缺失坐标")
        if not raw["items"] and raw["text"].strip():
            raise MediaError("OCR 有文字但未提供文字框")
        return raw["items"]
