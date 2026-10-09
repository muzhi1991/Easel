"""OpenAI speech protocol. Service extensions stay in this adapter."""
from __future__ import annotations
import io
import os
import tempfile
import wave
from pathlib import Path
import httpx
from .core import MediaError, SpeechRequest
from .http import client, json_response

class OpenAISpeechAdapter:
    descriptor = {
        'name': 'OpenAI 兼容语音合成', 'interface_version': 1,
        'channels': ['speech'], 'capabilities': ['generate_speech'],
        'fields': [
            {'key':'base_url','label':'Base URL（含 /v1）','type':'url','required':True},
            {'key':'model','label':'模型','type':'text','required':True},
            {'key':'voice','label':'默认音色','type':'text','default':'default'},
            {'key':'language','label':'语言（服务扩展，可留空）','type':'text','default':''},
            {'key':'instructions','label':'默认风格指令','type':'text','default':''},
            {'key':'expected_model_root','label':'权重名称校验（可留空）','type':'text','default':''},
            {'key':'api_key_env','label':'凭证环境变量（无鉴权留空）','type':'secret_ref','default':''},
            {'key':'timeout_seconds','label':'每次请求超时（秒）','type':'number','default':300,'min':1,'max':1800},
            {'key':'use_proxy','label':'使用环境代理','type':'boolean','default':False},
        ],
    }

    def concurrency_key(self, provider):
        return 'speech:' + provider['settings']['base_url']

    def models(self, c, settings):
        data = json_response(c.get(settings['base_url'] + '/models'))
        if not isinstance(data.get('data'), list):
            raise MediaError('服务模型列表格式不支持')
        model = next((m for m in data['data'] if isinstance(m, dict) and m.get('id') == settings['model']), None)
        if not model:
            raise MediaError('服务没有所选语音模型')
        expected = settings['expected_model_root']
        if expected and expected not in str(model.get('root', '')):
            raise MediaError('服务当前权重模式不匹配，请维护者确认；不会自动切换权重')
        return model

    def probe(self, provider):
        try:
            with client(provider['settings']) as c:
                model = self.models(c, provider['settings'])
            return {'ok':True,'detail':f"模型 {model['id']} 可用（非音质验证）"}
        except (MediaError, httpx.HTTPError) as exc:
            return {'ok':False,'detail':str(exc) if isinstance(exc, MediaError) else '语音服务连接失败'}

    def voices(self, provider):
        try:
            with client(provider['settings']) as c:
                data = json_response(c.get(provider['settings']['base_url'] + '/audio/voices'))
            values = data.get('voices')
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise MediaError('服务音色列表格式不支持')
            return values
        except httpx.HTTPError as exc:
            raise MediaError('无法读取服务音色列表（此扩展并非所有 OpenAI 服务都有）') from exc

    def submit(self, provider, capability, request: SpeechRequest):
        if capability != 'generate_speech' or not request.text.strip():
            raise MediaError('语音合成需要非空文本')
        s = provider['settings']
        payload = {'model':s['model'], 'input':request.text, 'voice':request.voice or s['voice'],
                   'response_format':'wav'}
        for key in ('language','instructions'):
            value = getattr(request,key) if getattr(request,key) is not None else s[key]
            if value:
                payload[key] = value
        try:
            with client(s) as c:
                if s['expected_model_root']:
                    self.models(c,s)
                r = c.post(s['base_url'] + '/audio/speech', json=payload)
                if not r.is_success:
                    raise MediaError(f'语音服务 HTTP {r.status_code}，未自动重试或切换供应商')
                content = r.content
        except httpx.TimeoutException as exc:
            raise MediaError('语音请求超时；服务可能仍在生成，未自动重试') from exc
        except httpx.HTTPError as exc:
            raise MediaError('语音服务连接失败，未自动重试') from exc
        try:
            with wave.open(io.BytesIO(content),'rb') as w:
                frames, rate = w.getnframes(), w.getframerate()
                if w.getcomptype() != 'NONE' or frames <= 0 or rate <= 0 or len(w.readframes(frames)) != frames * w.getnchannels() * w.getsampwidth():
                    raise ValueError('empty audio')
                duration = frames / rate
                channels = w.getnchannels()
        except (wave.Error, EOFError, ValueError) as exc:
            raise MediaError('语音服务没有返回有效的非空 PCM WAV，未保存伪音频') from exc
        out = Path(request.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.speech-',dir=out.parent)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(content)
            os.replace(name,out)
        finally:
            Path(name).unlink(missing_ok=True)
        return {'provider':provider['id'],'adapter':'openai-speech','backend':s['base_url'],
                'model':s['model'],'voice':payload['voice'],'output':str(out),'format':'wav',
                'duration':duration,'sample_rate':rate,'channels':channels}
