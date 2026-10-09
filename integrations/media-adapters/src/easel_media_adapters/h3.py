"""H3 native SGLang video protocol; all model-specific decisions live here."""
from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from .core import MediaError, VideoRequest


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.video-job-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def media_info(path):
    try:
        cp = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, text=True,
                            check=True, timeout=30)
        return json.loads(cp.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise MediaError(f'无法检查媒体文件 {path.name}；需要可用的 ffprobe') from exc


def data_uri(path, kind):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= 128 * 1024 * 1024:
        raise MediaError('输入素材必须是非空本地文件，单文件不超过128MiB')
    mime = mimetypes.guess_type(str(path))[0] or ''
    if not mime.startswith(kind + '/'):
        raise MediaError(f'{path.name} 的文件类型不是 {kind}')
    info = media_info(path)
    expected = 'video' if kind == 'image' else kind
    if not any(s.get('codec_type') == expected for s in info.get('streams', [])):
        raise MediaError(f'{path.name} 没有有效的{kind}内容')
    if kind == 'image':
        codec = next(s.get('codec_name') for s in info['streams'] if s.get('codec_type') == 'video')
        mime = {'png': 'image/png', 'mjpeg': 'image/jpeg', 'webp': 'image/webp'}.get(codec)
        if not mime:
            raise MediaError('图片仅支持PNG、JPEG和WebP')
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode(), info


class H3Adapter:
    descriptor = {
        'name': 'H3 原生视频（FL2VA / Ref2VA）', 'interface_version': 1,
        'channels': ['video'], 'capabilities': ['generate_video'],
        'fields': [
            {'key': 'base_url', 'label': 'Base URL（含 /v1）', 'type': 'url', 'required': True},
            {'key': 'variant', 'label': '模型类型', 'type': 'text', 'default': 'fl2va', 'choices': ['fl2va', 'ref2va']},
            {'key': 'model', 'label': '模型名（空=对应类型默认模型）', 'type': 'text'},
            {'key': 'timeout_seconds', 'label': '任务等待超时（秒）', 'type': 'number', 'default': 1800, 'min': 1, 'max': 7200},
            {'key': 'poll_seconds', 'label': '查询间隔（秒）', 'type': 'number', 'default': 3, 'min': 1, 'max': 30},
            {'key': 'use_proxy', 'label': '使用环境代理', 'type': 'boolean', 'default': False},
            {'key': 'api_key_env', 'label': '凭证环境变量名（无鉴权留空）', 'type': 'secret_ref'},
        ],
    }

    def concurrency_key(self, provider):
        # These instances share GPU resources with each other; serialize our video tasks.
        return 'h3-video'

    def capabilities(self, provider):
        ref = provider['settings']['variant'] == 'ref2va'
        return {'native_audio': True, 'audio_default': True, 'dialogue': False,
                'dialogue_faithful': False, 'audio_reference': ref,
                'first_frame': not ref, 'last_frame': not ref, 'reference_images': ref,
                'reference_video': ref, 'model': self.model(provider)}

    def model(self, provider):
        return provider['settings'].get('model') or (
            'MiniMax-H3-Ref2VA-Turbo' if provider['settings']['variant'] == 'ref2va' else 'MiniMax-H3-Turbo')

    def client(self, provider):
        s = provider['settings']
        key = os.environ.get(s.get('api_key_env') or '', '')
        if s.get('api_key_env') and not key:
            raise MediaError('配置的 H3 凭证环境变量未设置')
        return httpx.Client(trust_env=s['use_proxy'], follow_redirects=False,
                            timeout=httpx.Timeout(180, connect=10),
                            headers={'Authorization': f'Bearer {key}'} if key else {})

    def probe(self, provider):
        try:
            with self.client(provider) as http:
                response = http.get(provider['settings']['base_url'].removesuffix('/v1') + '/health', timeout=10)
                response.raise_for_status()
                ok = response.json().get('status') == 'ok'
                return {'ok': ok, 'detail': '仅服务探活，未验证视频生成质量'}
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaError('H3 探活失败，请检查地址、鉴权及服务状态') from exc

    def payload(self, provider, request):
        if not isinstance(request, VideoRequest):
            raise MediaError('H3 需要 VideoRequest')
        if not request.prompt.strip():
            raise MediaError('视频提示词不能为空')
        if not isinstance(request.duration, int) or not 4 <= request.duration <= 15:
            raise MediaError('H3 视频时长需为4–15秒整数')
        if request.ratio not in ('16:9', '9:16', '1:1', '4:3', '3:4'):
            raise MediaError('请显式使用支持的画幅比例：16:9、9:16、1:1、4:3、3:4')
        if request.audio not in ('auto', 'on'):
            raise MediaError('H3 当前未确认关闭原生音频的接口；不能静默忽略 audio=off')
        if request.seed is not None and (not isinstance(request.seed, int) or not 0 <= request.seed < 2**63):
            raise MediaError('seed需为0至2^63-1的整数')
        ref = provider['settings']['variant'] == 'ref2va'
        references = request.reference_images + request.reference_videos + request.reference_audio
        if ref and (request.first_frame or request.last_frame):
            raise MediaError('当前 Ref2VA 实例使用参考素材；首尾帧请显式选择 FL2VA 实例')
        if ref and not references:
            raise MediaError('Ref2VA 至少需要一份参考图片、视频或音频')
        if not ref and references:
            raise MediaError('FL2VA 不接受参考素材，请显式选择 Ref2VA 实例')
        if len(request.reference_images) > 9 or len(request.reference_videos) > 3 or len(request.reference_audio) > 3 or len(references) > 12:
            raise MediaError('参考素材上限：9图片、3视频、3音频，合计12份')
        paths = [p for p in (request.first_frame, request.last_frame) if p] + list(references)
        if sum(Path(p).stat().st_size for p in paths if Path(p).is_file()) > 256 * 1024 * 1024:
            raise MediaError('参考素材总大小不能超过256MiB')
        conditions = []
        for path, frame in ((request.first_frame, 0), (request.last_frame, -1)):
            if path:
                uri, _ = data_uri(path, 'image')
                conditions.append({'type': 'image', 'uri': uri, 'role': 'keyframe', 'frame_index': frame})
        for kind, sources in (('image', request.reference_images), ('video', request.reference_videos), ('audio', request.reference_audio)):
            total = 0
            for path in sources:
                uri, info = data_uri(path, kind)
                if kind != 'image':
                    duration = float(info.get('format', {}).get('duration', 0))
                    if not math.isfinite(duration) or not 2 <= duration <= 15:
                        raise MediaError('参考视频/音频每段需为2–15秒')
                    total += duration
                conditions.append({'type': kind, 'uri': uri, 'role': 'reference'})
            if total > 15:
                raise MediaError('同类参考视频或音频总时长不能超过15秒')
        payload = {'model': request.model or self.model(provider), 'prompt': request.prompt,
                   'task': 'ref2va' if ref else 'fl2va' if conditions else 't2va',
                   'conditions': conditions,
                   'target': {'short_edge': 768, 'aspect_ratio': request.ratio, 'duration_seconds': request.duration},
                   'num_inference_steps': 9, 'flow_shift': 12 if ref else 6,
                   'audio_flow_shift': 3, 'quality': 'lossless'}
        if request.seed is not None:
            payload['seed'] = request.seed
        return payload

    def submit(self, provider, capability, request):
        if capability != 'generate_video':
            raise MediaError('H3 不支持该能力')
        output = Path(request.output)
        record_path = output.with_suffix(output.suffix + '.job.json')
        base = provider['settings']['base_url']
        budget = request.timeout if request.timeout is not None else provider['settings']['timeout_seconds']
        if not math.isfinite(budget) or not 0 < budget <= 7200:
            raise MediaError('视频等待超时需大于0且不超过7200秒')
        if request.resume:
            try:
                record = json.loads(record_path.read_text())
            except (OSError, ValueError) as exc:
                raise MediaError('未找到有效任务记录；无法恢复查询') from exc
            if record.get('provider') != provider['id'] or record.get('base_url') != base:
                raise MediaError('恢复任务的供应商或地址与记录不同')
        else:
            if output.exists() and not record_path.exists():
                raise MediaError('输出文件已存在，请选择新的输出路径')
            if record_path.exists():
                raise MediaError('输出位置已有任务记录；请用 --resume 或选择新的输出路径，勿重复提交')
            payload = self.payload(provider, request)
            record = {'provider': provider['id'], 'adapter': 'h3-video', 'base_url': base,
                      'model': payload['model'], 'task': payload['task'], 'seed': request.seed,
                      'status': 'submitting', 'backend': base, 'request': {k: v for k, v in payload.items() if k != 'conditions'}}
            # Keep evidence even if submission status is unknown after a disconnect.
            atomic_json(record_path, record)
        job_id = record.get('id')
        try:
            with self.client(provider) as http:
                if not request.resume:
                    response = http.post(base + '/videos', json=payload)
                    response.raise_for_status()
                    job_id = response.json().get('id')
                    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', job_id):
                        raise MediaError('服务未返回有效任务ID；请检查服务端记录，不重交')
                    record.update(id=job_id, status='queued')
                    atomic_json(record_path, record)
                if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', job_id):
                    raise MediaError('提交结果未知，没有可查询ID；请检查服务日志，不重交')
                deadline = time.monotonic() + budget
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MediaError(f'视频等待超时，任务可能仍运行：{job_id}；使用 --resume 继续查询，不重交')
                    response = http.get(f'{base}/videos/{job_id}', timeout=min(30, remaining))
                    response.raise_for_status()
                    status = response.json().get('status')
                    record['status'] = status
                    atomic_json(record_path, record)
                    if status == 'completed':
                        break
                    if status in ('failed', 'cancelled', 'canceled'):
                        raise MediaError(f'H3任务{status}：{job_id}；请检查服务端错误')
                    if status not in ('queued', 'in_progress', 'pending', 'running'):
                        raise MediaError(f'H3返回未知任务状态：{status}；不重交')
                    time.sleep(min(provider['settings']['poll_seconds'], max(0, deadline - time.monotonic())))
                output.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix='.video-', suffix='.mp4', dir=output.parent)
                try:
                    with os.fdopen(fd, 'wb') as dest, http.stream('GET', f'{base}/videos/{job_id}/content', timeout=300) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            dest.write(chunk)
                    info = media_info(Path(name))
                    if not any(s.get('codec_type') == 'video' for s in info.get('streams', [])):
                        raise MediaError('下载内容没有有效视频流，不交付成功文件')
                    os.replace(name, output)
                finally:
                    Path(name).unlink(missing_ok=True)
                record['output'] = str(output)
                atomic_json(record_path, record)
                return record
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise MediaError(f'H3请求失败，任务ID={job_id or "未知"}；已保留任务记录，不重交') from exc
