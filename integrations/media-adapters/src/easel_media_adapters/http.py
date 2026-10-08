"""No implicit retries of submissions; explicit proxy and credential policy."""
import os
import json
import subprocess
import tempfile
from pathlib import Path

import httpx

from .core import MediaError


def client(settings: dict) -> httpx.Client:
    headers = {}
    ref = settings.get("api_key_env")
    if ref:
        key = os.environ.get(ref, "").strip()
        if not key:
            raise MediaError(f"未配置凭证环境变量 {ref}")
        headers["Authorization"] = f"Bearer {key}"
    if settings.get("transport") == "curl":
        return CurlClient(settings, headers)
    return httpx.Client(timeout=settings.get("timeout_seconds", 180),
                        trust_env=settings.get("use_proxy", False), headers=headers,
                        follow_redirects=False)


class CurlClient:
    """Explicit native transport for hosts where Python lacks LAN permission.

    Credentials go through stdin configuration, never process command arguments.
    Requests are never retried or redirected, including uploads.
    """

    def __init__(self, settings, headers):
        self.settings, self.headers = settings, headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url):
        return self._request("GET", url)

    def post(self, url, *, data, files):
        return self._request("POST", url, data, files)

    def _request(self, method, url, data=None, files=None):
        with tempfile.TemporaryDirectory(prefix="easel-http-") as tmp:
            output = Path(tmp) / "response"
            lines = ["silent", "show-error", f"url = {json.dumps(url)}", f"request = {json.dumps(method)}",
                     f"max-time = {self.settings.get('timeout_seconds', 180)}", "connect-timeout = 10",
                     f"output = {json.dumps(str(output))}", 'write-out = "%{http_code}"']
            if not self.settings.get("use_proxy", False):
                lines.append('noproxy = "*"')
            for key, val in self.headers.items():
                lines.append(f"header = {json.dumps(key + ': ' + val)}")
            for key, val in (data or {}).items():
                lines.append(f"form-string = {json.dumps(key + '=' + str(val), ensure_ascii=False)}")
            for key, (filename, handle, content_type) in (files or {}).items():
                # Private numeric filenames avoid curl form syntax in caller-controlled paths.
                part = Path(tmp) / f"upload-{len(lines)}"
                part.write_bytes(handle.read())
                lines.append(f"form = {json.dumps(key + '=@' + str(part) + ';type=' + content_type)}")
            try:
                proc = subprocess.run(["/usr/bin/curl" if Path("/usr/bin/curl").exists() else "curl", "--config", "-"],
                                      input="\n".join(lines) + "\n", capture_output=True, text=True,
                                      timeout=self.settings.get("timeout_seconds", 180) + 10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise MediaError(f"原生 curl 传输失败：{exc}") from exc
            if proc.returncode:
                raise MediaError(f"原生 curl 请求失败（code={proc.returncode}），请检查网络；没有重交任务")
            return httpx.Response(int(proc.stdout), content=output.read_bytes(), request=httpx.Request(method, url))


def json_response(response: httpx.Response) -> dict:
    if not response.is_success:
        # Do not expose arbitrary response bodies (may include credentials or request audio).
        hint = {429: "服务忙，请稍后重试", 422: "服务拒绝输入，请检查音频、语言或长度", 503: "服务不可用或显存不足"}.get(response.status_code, "检查服务地址、鉴权及服务日志")
        raise MediaError(f"上游 HTTP {response.status_code}：{hint}（不自动切换供应商）")
    try:
        value = response.json()
    except ValueError as exc:
        raise MediaError("上游没有返回 JSON") from exc
    if not isinstance(value, dict):
        raise MediaError("上游响应必须是 JSON 对象")
    return value
