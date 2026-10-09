"""YuE2 asynchronous jobs; model-specific protocol stays outside Easel."""
from __future__ import annotations

import json
import hashlib
from contextlib import ExitStack, contextmanager
import math
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from .core import MediaError, MusicRequest, file_lock
from .http import client, json_response

# These are transport budgets, independent of the configured job waiting budget.
QUERY_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300
MAX_AUDIO_BYTES = 512 * 1024 * 1024
MAX_SCORE_BYTES = 1024 * 1024
# Leave room for UTF-8 fields and multipart overhead within the service 40 MiB limit.
MAX_REFERENCE_BYTES = 40 * 1024 * 1024 - 256 * 1024


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.music-record-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def audio_info(path: Path) -> dict:
    try:
        cp = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, text=True,
                            check=True, timeout=QUERY_TIMEOUT)
        info = json.loads(cp.stdout)
        streams = [s for s in info['streams'] if s.get('codec_type') == 'audio']
        duration = float(info['format']['duration'])
        if not streams or not math.isfinite(duration) or duration <= 0:
            raise ValueError('empty audio')
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                       capture_output=True, check=True, timeout=DOWNLOAD_TIMEOUT)
        return {'duration': duration, 'sample_rate': int(streams[0]['sample_rate']),
                'channels': streams[0]['channels'], 'codec': streams[0]['codec_name']}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as exc:
        raise MediaError('音乐下载内容无效或无法完整解码；需要 FFmpeg/ffprobe，不交付伪音频') from exc


class YuE2Adapter:
    descriptor = {
        'name': 'YuE2 原生音乐作业', 'interface_version': 1,
        'channels': ['music'], 'capabilities': ['generate_music'],
        'fields': [
            {'key': 'base_url', 'label': '服务根地址（不含 /v1）', 'type': 'url', 'required': True},
            {'key': 'model', 'label': '模型', 'type': 'text', 'default': 'YuE2-3B', 'choices': ['YuE2-3B']},
            {'key': 'cot', 'label': '默认谱面规划', 'type': 'text', 'default': 'full', 'choices': ['full', 'melody', 'off']},
            {'key': 'api_key_env', 'label': '凭证环境变量名', 'type': 'secret_ref', 'required': True},
            {'key': 'timeout_seconds', 'label': '等待超时（含排队，秒）', 'type': 'number', 'default': 3600, 'min': 1, 'max': 7200},
            {'key': 'poll_seconds', 'label': '查询间隔（秒）', 'type': 'number', 'default': 5, 'min': 1, 'max': 30},
            {'key': 'use_proxy', 'label': '使用环境代理', 'type': 'boolean', 'default': False},
        ],
    }

    def concurrency_key(self, provider):
        return 'music:' + provider['settings']['base_url']

    def probe(self, provider):
        try:
            with client(provider['settings']) as c:
                r = json_response(c.get(provider['settings']['base_url'] + '/health/ready', timeout=10))
                if r.get('status') != 'ready':
                    return {'ok': False, 'detail': '音乐服务尚未就绪'}
                # The readiness endpoint is public; validate auth without creating a job.
                auth = c.get(provider['settings']['base_url'] + '/v1/jobs/easel-auth-probe', timeout=10)
                if auth.status_code != 404:
                    return {'ok': False, 'detail': f'作业接口鉴权检查 HTTP {auth.status_code}'}
            return {'ok': True, 'detail': '服务就绪、鉴权通过（未验证模型身份或歌曲效果）'}
        except (MediaError, httpx.HTTPError, ValueError):
            return {'ok': False, 'detail': '音乐服务连接、凭证或就绪检查失败'}

    def payload(self, provider, request):
        if not isinstance(request, MusicRequest):
            raise MediaError('音乐生成需要 MusicRequest')
        if request.duration is not None and (
                isinstance(request.duration, bool) or not isinstance(request.duration, (int, float))
                or not math.isfinite(request.duration) or not 10 <= request.duration <= 180):
            raise MediaError('目标生成时长需为10–180秒，不保证输出严格等长')
        if request.model and request.model != provider['settings']['model']:
            raise MediaError('此服务使用固定部署模型，不支持请求切换模型')
        if not request.prompt.strip() or len(request.prompt) > 2000:
            raise MediaError('YuE2 风格提示词需为1–2000字符')
        lyrics = request.lyrics or ''
        if request.instrumental:
            if lyrics.strip():
                raise MediaError('纯 BGM 不能带歌词正文，请省略歌词')
            lyrics = ''
        elif not lyrics.strip() or len(lyrics) > 16000:
            raise MediaError('歌曲或有人声翻唱需要1–16000字符歌词')
        if request.reference_audio is not None and (request.cot is not None or request.abc is not None):
            raise MediaError('录音翻唱由服务转谱，不能同时指定cot或ABC乐谱')
        cot = request.cot or provider['settings']['cot']
        if request.instrumental and cot == 'off' and request.reference_audio is None:
            raise MediaError('纯 BGM 需要乐谱规划，cot不能为off')
        if cot not in ('full', 'melody', 'off'):
            raise MediaError('谱面规划仅支持 full、melody、off')
        if request.abc is not None and (cot == 'off' or not request.abc.strip() or len(request.abc) > 64000):
            raise MediaError('ABC乐谱需为1–64000字符，且规划不能为off')
        seed = request.seed if request.seed is not None else secrets.randbelow(2**63)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
            raise MediaError('seed需为0至2^63-1的整数')
        result = {'style': request.prompt, 'lyrics': request.lyrics, 'cot': cot, 'seed': seed, 'n': 1}
        if request.abc is not None:
            result['abc'] = request.abc
        if request.instrumental:
            result.pop('lyrics')
            result['instrumental'] = True
        if request.duration is not None:
            result.update(duration_seconds=request.duration, duration_mode='target')
        if request.reference_audio is not None:
            # Cover endpoint performs its own transcription; it accepts neither cot nor n.
            result.pop('cot')
            result.pop('n')
        return result

    @contextmanager
    def reference_snapshot(self, source):
        source = Path(source)
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_REFERENCE_BYTES:
            raise MediaError('参考录音须为非空本地文件，需为40MiB请求上限预留256KiB')
        with tempfile.TemporaryDirectory(prefix='easel-music-reference-') as tmp:
            snapshot = Path(tmp) / ('reference' + source.suffix.lower())
            size, digest = 0, hashlib.sha256()
            with source.open('rb') as src, snapshot.open('wb') as dst:
                while chunk := src.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_REFERENCE_BYTES:
                        raise MediaError('参考录音超过上传大小上限')
                    digest.update(chunk)
                    dst.write(chunk)
            info = audio_info(snapshot)
            if info['duration'] > 180:
                raise MediaError('参考录音不能超过180秒，请明确选取片段后再上传')
            yield snapshot, {'path': str(source.resolve()), 'sha256': digest.hexdigest(),
                             'bytes': size, **info}


    def submit(self, provider, capability, request):
        if capability != 'generate_music' or not isinstance(request, MusicRequest):
            raise MediaError('YuE2 不支持该能力或输入')
        output = Path(request.output)
        # Protect an output's job record even when two different instances target it.
        with file_lock(output.with_suffix(output.suffix + '.lock')):
            return self._generate(provider, request, output)

    def _generate(self, provider, request, output):
        with ExitStack() as resources:
            return self._run(provider, request, output, resources)

    def _run(self, provider, request, output, resources):
        if output.suffix.lower() not in ('.flac', '.mp3', '.wav', '.m4a'):
            raise MediaError('音乐输出扩展名需为flac、mp3、wav或m4a')
        s = provider['settings']
        base = s['base_url']
        if not os.environ.get(s['api_key_env'], '').strip():
            raise MediaError('未配置音乐凭证环境变量，不提交任务')
        if base.endswith('/v1'):
            raise MediaError('YuE2 请填写服务根地址，不含 /v1')
        budget = request.timeout if request.timeout is not None else s['timeout_seconds']
        if not math.isfinite(budget) or not 0 < budget <= 7200:
            raise MediaError('音乐等待超时需大于0且不超过7200秒')
        poll = request.poll_interval if request.poll_interval is not None else s['poll_seconds']
        if not math.isfinite(poll) or not 1 <= poll <= 30:
            raise MediaError('音乐查询间隔需为1–30秒')
        record_path = output.with_suffix(output.suffix + '.job.json')
        native = output if output.suffix.lower() == '.flac' else output.with_suffix('.flac')
        score = output.with_suffix('.abc')
        metadata = output.with_suffix('.music.json')
        snapshot = None
        if request.resume:
            try:
                record = json.loads(record_path.read_text())
                if not isinstance(record, dict):
                    raise ValueError('invalid record')
            except (OSError, ValueError) as exc:
                raise MediaError('没有有效任务记录，无法恢复查询') from exc
            if (record.get('provider'), record.get('adapter'), record.get('base_url'), record.get('output')) != (
                    provider['id'], 'yue2-music', base, str(output)):
                raise MediaError('恢复供应商、服务地址或输出与任务记录不同')
            payload = record.get('request')
            if (not isinstance(payload, dict) or (record.get('operation', 'generate') != 'cover'
                    and payload.get('cot') not in ('full', 'melody', 'off'))):
                raise MediaError('任务记录缺少有效原请求，不能恢复')
        else:
            if any(p.exists() for p in (record_path, output, native, score, metadata)):
                raise MediaError('输出或任务记录已存在，请用 --resume 或新路径，勿重复提交')
            payload = self.payload(provider, request)
            reference = None
            if request.reference_audio is not None:
                snapshot, reference = resources.enter_context(self.reference_snapshot(request.reference_audio))
            record = {'provider': provider['id'], 'adapter': 'yue2-music', 'base_url': base,
                      'model': s['model'], 'model_source': 'deployment_configuration',
                      'output': str(output), 'request': payload,
                      'operation': 'cover' if reference else 'generate', 'reference_audio': reference,
                      'idempotency_key': uuid.uuid4().hex, 'status': 'submitting'}
            # No credential/header is included in any artifact.
            atomic_json(record_path, record)
        job_id = record.get('id')
        try:
            with client(s) as c:
                if not request.resume:
                    headers = {'Idempotency-Key': record['idempotency_key']}
                    if snapshot is not None:
                        fields = {k: ('true' if v is True else 'false' if v is False else str(v))
                                  for k, v in payload.items()}
                        with snapshot.open('rb') as audio:
                            data = json_response(c.post(base + '/v1/covers', data=fields,
                                files={'audio': (snapshot.name, audio, 'application/octet-stream')},
                                headers=headers, timeout=DOWNLOAD_TIMEOUT))
                    else:
                        data = json_response(c.post(base + '/v1/jobs', json=payload,
                                                    headers=headers, timeout=QUERY_TIMEOUT))
                    job_id = data.get('id')
                    if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
                        raise MediaError('提交未返回有效ID；保留幂等键，请维护者查服务记录，不换键重交')
                    record.update(id=job_id, status=data.get('status', 'queued'))
                    atomic_json(record_path, record)
                if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', job_id):
                    raise MediaError('提交结果未知，只有幂等键无ID；请维护者核查服务，不自动重交')
                deadline = time.monotonic() + budget
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MediaError(f'音乐等待超时，任务可能仍运行：{job_id}；用 --resume 继续查询')
                    data = json_response(c.get(f'{base}/v1/jobs/{job_id}', timeout=min(QUERY_TIMEOUT, remaining)))
                    if data.get('id') != job_id:
                        raise MediaError('查询返回的任务ID不匹配')
                    status = data.get('status')
                    record.update(status=status, stage=data.get('stage'), result=data.get('result'))
                    atomic_json(record_path, record)
                    if status == 'succeeded':
                        result = data.get('result')
                        flags = result.get('truncated', {}) if isinstance(result, dict) else {}
                        if not isinstance(result, dict) or not isinstance(flags, dict) or flags.get('abc') is not False or flags.get('semantic') is not False:
                            raise MediaError('歌曲结果缺失或有截断标记，不能当作完整生成')
                        break
                    if status in ('truncated', 'failed', 'cancelled'):
                        raise MediaError(f'YuE2任务{status}：{job_id}；保留任务记录，不交付完整歌曲')
                    if status not in ('queued', 'running'):
                        raise MediaError('服务返回未知任务状态，不重交')
                    time.sleep(min(poll, max(0, deadline - time.monotonic())))
                with tempfile.TemporaryDirectory(prefix='.music-', dir=output.parent) as tmp:
                    tmp = Path(tmp)
                    flac = tmp / 'song.flac'
                    self.download(c, f'{base}/v1/jobs/{job_id}/audio', flac, MAX_AUDIO_BYTES)
                    with flac.open('rb') as f:
                        if f.read(4) != b'fLaC':
                            raise MediaError('音乐接口未返回FLAC，不保存错误响应为音频')
                    info = audio_info(flac)
                    seconds = result.get('audio_seconds')
                    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or abs(seconds - info['duration']) > max(1, info['duration'] * .02):
                        raise MediaError('下载音频时长与服务结果不符，不交付')
                    staged_score = tmp / 'score.abc'
                    has_score = record.get('operation') == 'cover' or payload.get('cot') != 'off'
                    if has_score:
                        self.download(c, f'{base}/v1/jobs/{job_id}/score', staged_score, MAX_SCORE_BYTES)
                        text = staged_score.read_text(encoding='utf-8')
                        if not re.search(r'^X:', text, re.M) or not re.search(r'^K:', text, re.M):
                            raise MediaError('服务没有返回有效ABC乐谱，不交付伪乐谱')
                    final = flac
                    if output != native:
                        final = tmp / ('song' + output.suffix.lower())
                        self.convert(flac, final)
                        converted = audio_info(final)
                        if abs(converted['duration'] - info['duration']) > 1:
                            raise MediaError('转码后音频时长不符')
                    if output != native:
                        os.replace(flac, native)
                    os.replace(final, output)
                    if staged_score.exists():
                        os.replace(staged_score, score)
                target = payload.get('duration_seconds')
                record.update(audio=info, native_output=str(native), score=str(score) if has_score else None,
                              duration_target=target, duration_actual=info['duration'],
                              duration_deviation=info['duration'] - target if target is not None else None)
                atomic_json(record_path, record)
                atomic_json(metadata, record)
                return record
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise MediaError(f'音乐请求或保存失败，任务ID={job_id or "未知"}；保留记录，不自动重交或切换供应商') from exc

    @staticmethod
    def download(c, url, path, limit):
        size = 0
        with path.open('wb') as out, c.stream('GET', url, timeout=DOWNLOAD_TIMEOUT) as response:
            if not response.is_success:
                raise MediaError(f'音乐下载HTTP {response.status_code}；可用 --resume 重查下载')
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise MediaError('音乐下载超过客户端大小上限')
                out.write(chunk)
            if not size:
                raise MediaError('音乐下载为空')

    @staticmethod
    def convert(source, target):
        codecs = {'.mp3': ['-c:a', 'libmp3lame', '-q:a', '2'], '.wav': ['-c:a', 'pcm_s16le'],
                  '.m4a': ['-c:a', 'aac', '-b:a', '192k']}
        try:
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(source),
                            *codecs[target.suffix], str(target)], capture_output=True, check=True,
                           timeout=DOWNLOAD_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MediaError('音乐本地转码失败；保留任务ID，可恢复下载') from exc
