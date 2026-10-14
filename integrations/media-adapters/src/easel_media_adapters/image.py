"""Synchronous OpenAI Images protocol; selection policy belongs to the caller."""
from __future__ import annotations

import base64
import binascii
import io
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from .core import ImageRequest, MediaError
from .http import client, json_response


class OpenAIImageAdapter:
    descriptor = {
        'name': 'OpenAI 兼容生图', 'interface_version': 1,
        'channels': ['image'], 'capabilities': ['generate_image'],
        'fields': [
            {'key': 'base_url', 'label': 'Base URL（含 /v1）', 'type': 'url', 'required': True},
            {'key': 'model', 'label': '模型', 'type': 'text', 'required': True},
            {'key': 'supports_edit', 'label': '支持图片编辑', 'type': 'boolean', 'default': False},
            {'key': 'api_key_env', 'label': '凭证环境变量（无鉴权留空）', 'type': 'secret_ref', 'default': ''},
            {'key': 'timeout_seconds', 'label': '生成超时（秒）', 'type': 'number', 'default': 1800, 'min': 1, 'max': 3600},
            {'key': 'transport', 'label': 'HTTP 传输', 'type': 'text', 'default': 'httpx', 'choices': ['httpx', 'curl']},
            {'key': 'use_proxy', 'label': '使用环境代理', 'type': 'boolean', 'default': False},
        ],
    }

    def probe(self, provider):
        try:
            with client(provider['settings']) as c:
                data = json_response(c.get(provider['settings']['base_url'] + '/models'))
            found = any(isinstance(m, dict) and m.get('id') == provider['settings']['model']
                        for m in data.get('data', []))
            return {'ok': found, 'detail': '模型已登记（未验证生图或额度）' if found else '未找到配置的模型'}
        except (MediaError, httpx.HTTPError):
            return {'ok': False, 'detail': '无法查询生图模型列表，请检查地址和凭证'}

    def submit(self, provider, capability, request: ImageRequest):
        s = dict(provider['settings'])
        if capability != 'generate_image' or not request.prompt.strip():
            raise MediaError('生图需要非空提示词')
        if not 1 <= request.n <= 10 or request.format not in ('png', 'jpeg', 'webp'):
            raise MediaError('图片数量需为 1–10，格式需为 png/jpeg/webp')
        if request.image and not s['supports_edit']:
            raise MediaError('此实例未声明图片编辑能力；不能用文生图替代编辑')
        if request.mask and not request.image:
            raise MediaError('遮罩必须与输入图片一起使用')
        if request.timeout is not None:
            if not 1 <= request.timeout <= 3600:
                raise MediaError('生图超时需为 1–3600 秒')
            s['timeout_seconds'] = request.timeout
        payload = {'model': s['model'], 'prompt': request.prompt, 'size': request.size, 'n': request.n}
        if request.quality:
            payload['quality'] = request.quality
        try:
            with client(s) as c, ExitStack() as stack:
                if request.image:
                    files = {}
                    for key, path in (('image', request.image), ('mask', request.mask)):
                        if path:
                            path = Path(path)
                            files[key] = (path.name, stack.enter_context(path.open('rb')), 'application/octet-stream')
                    r = c.post(s['base_url'] + '/images/edits', data={k: str(v) for k, v in payload.items()}, files=files)
                else:
                    r = c.post(s['base_url'] + '/images/generations', json=payload)
                if not r.is_success:
                    # Only explicit machine-readable quota codes qualify. 429 alone is rate limiting.
                    try:
                        error = r.json().get('error', {})
                        codes = {str(error.get('code')), str(error.get('type'))} if isinstance(error, dict) else set()
                    except (ValueError, AttributeError, TypeError):
                        codes = set()
                    if codes & {'insufficient_quota', 'quota_exceeded', 'billing_hard_limit_reached', 'insufficient_balance'}:
                        raise MediaError('IMAGE_QUOTA_EXHAUSTED：上游明确报告额度不足；可按用户策略选择其他生图实例')
                    raise MediaError(f'生图服务 HTTP {r.status_code}；未自动重试或切换模型，429 不等于额度不足')
                data = json_response(r).get('data')
            if not isinstance(data, list) or len(data) != request.n:
                raise MediaError('生图返回数量与请求不符；未自动补交任务')
            images = []
            for item in data:
                if not isinstance(item, dict):
                    raise MediaError('生图结果格式无效')
                if item.get('b64_json'):
                    raw = base64.b64decode(item['b64_json'], validate=True)
                else:
                    url = item.get('url', '')
                    if urlsplit(url).scheme not in ('https', 'http'):
                        raise MediaError('生图结果缺少有效图片')
                    # Download without the API credential; image URLs may point to a separate CDN.
                    with client({**s, 'api_key_env': ''}) as downloader:
                        response = downloader.get(url)
                        response.raise_for_status()
                        raw = response.content
                with Image.open(io.BytesIO(raw)) as im:
                    im.load()
                    encoded = io.BytesIO()
                    (im.convert('RGB') if request.format == 'jpeg' else im).save(encoded, format=request.format.upper())
                    images.append(encoded.getvalue())
        except httpx.TimeoutException as exc:
            raise MediaError('生图请求超时，任务可能仍在生成；不要重交或切换模型') from exc
        except httpx.HTTPError as exc:
            raise MediaError('生图或下载连接失败，提交状态可能未知；不要自动重交') from exc
        except (UnidentifiedImageError, binascii.Error, ValueError, TypeError, OSError) as exc:
            raise MediaError('生图结果不是有效图片，或文件读写失败；不要自动重交') from exc
        output = Path(request.output)
        paths = ([output] if request.n == 1 and output.suffix else
                 [output.with_name(f'{output.stem}-{i+1}.{request.format}') for i in range(request.n)] if output.suffix else
                 [output / f'image-{i+1}.{request.format}' for i in range(request.n)])
        paths = [p.with_suffix('.' + request.format) for p in paths]
        for path, raw in zip(paths, images):
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.image-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(raw)
                os.replace(name, path)
            finally:
                Path(name).unlink(missing_ok=True)
        return {'provider': provider['id'], 'model': s['model'], 'outputs': [str(p) for p in paths]}
