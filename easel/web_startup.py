"""Start and monitor the selected local gateway with the LAN Web launcher."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import urllib.request

from easel.direct_api import read_settings
from easel.gateway_endpoint import healthz_url
from easel.harnesses.store import settings
from easel.runtime_env import web_environment
from easel.timeouts import (TIMEOUT_GATEWAY_CHECK, TIMEOUT_GATEWAY_PROBE,
                            TIMEOUT_GATEWAY_START, TIMEOUT_WEB_SHUTDOWN)

GATEWAY_CHECK_INTERVAL = TIMEOUT_GATEWAY_CHECK


def _uses_gateway(root: Path) -> bool:
    return settings(root / 'outputs', read_settings(root / '.env'))['runtime'] == 'openclaw'


def _check_gateway() -> None:
    with urllib.request.urlopen(healthz_url(), timeout=TIMEOUT_GATEWAY_PROBE) as response:
        if response.status != 200:
            raise RuntimeError('Easel OpenClaw gateway is not ready')


def ensure_gateway(root: Path, environment: dict[str, str], *, recovery: bool = False) -> bool:
    if not _uses_gateway(root):
        return False
    command = ['bash', str(root / 'scripts/gateway.sh'), 'start']
    if recovery:
        # A failed health probe must never force-kill a busy/draining listener.
        command.append('--no-force')
    subprocess.run(command, cwd=root, env=environment, check=True,
                   timeout=TIMEOUT_GATEWAY_START)
    # gateway.sh historically exits zero on timeout; verify the actual service.
    _check_gateway()
    return True


def supervise_web(root: Path, environment: dict[str, str], arguments: list[str]) -> int:
    """Recover a vanished gateway, including one reused just before its shutdown.

    Keep the Web child in its own process group so signals also reach its Python
    server grandchild. Recovery never resubmits a conversation or restarts Web.
    """
    stopped = False
    web = None

    def forward(signum, _frame):
        nonlocal stopped
        stopped = True
        if web is not None and web.poll() is None:
            try:
                os.killpg(web.pid, signum)
            except ProcessLookupError:
                pass

    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        web = subprocess.Popen(arguments, cwd=root, env=environment, start_new_session=True)
        while not stopped:
            try:
                return web.wait(timeout=GATEWAY_CHECK_INTERVAL)
            except subprocess.TimeoutExpired:
                pass
            if stopped or not _uses_gateway(root):
                continue
            try:
                _check_gateway()
            except (OSError, RuntimeError):
                if stopped:
                    break
                print('[easel] 专用网关失联，尝试恢复（不重放对话）…', file=sys.stderr, flush=True)
                try:
                    ensure_gateway(root, environment, recovery=True)
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    print(f'[easel] 网关恢复未完成（{type(error).__name__}），稍后重试；'
                          '请检查 /tmp/easel-gateway.log', file=sys.stderr, flush=True)
                else:
                    print('[easel] 专用网关已恢复', file=sys.stderr, flush=True)
        return web.wait(timeout=TIMEOUT_WEB_SHUTDOWN)
    finally:
        if web is not None and web.poll() is None:
            try:
                os.killpg(web.pid, signal.SIGTERM)
                web.wait(timeout=TIMEOUT_WEB_SHUTDOWN)
            except subprocess.TimeoutExpired:
                os.killpg(web.pid, signal.SIGKILL)
                web.wait()
            except ProcessLookupError:
                pass
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    root = Path.cwd()
    environment = web_environment(dict(os.environ))
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment['PATH']
    try:
        managed = ensure_gateway(root, environment)
    except Exception as error:
        print(f'[easel] 专用网关启动失败（{type(error).__name__}），请检查 /tmp/easel-gateway.log', file=sys.stderr)
        raise SystemExit(1)
    arguments = [str(root / '.venv/bin/easel'), 'web', *sys.argv[1:]]
    if managed:
        raise SystemExit(supervise_web(root, environment, arguments))
    os.execve(arguments[0], ['easel', *arguments[1:]], environment)


if __name__ == '__main__':
    main()
