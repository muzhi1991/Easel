"""Start the selected local gateway before the LAN Web launcher."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import urllib.request

from easel.direct_api import read_settings
from easel.gateway_endpoint import healthz_url
from easel.harnesses.store import settings
from easel.runtime_env import web_environment


def ensure_gateway(root: Path, environment: dict[str, str]) -> None:
    if settings(root / 'outputs', read_settings(root / '.env'))['runtime'] != 'openclaw':
        return
    subprocess.run(['bash', str(root / 'scripts/gateway.sh'), 'start'],
                   cwd=root, env=environment, check=True)
    # gateway.sh waits for readiness but historically exits zero on timeout.
    # Fail the launcher so launchd retries instead of leaving a disconnected Web UI.
    with urllib.request.urlopen(healthz_url(), timeout=3) as response:
        if response.status != 200:
            raise RuntimeError('Easel OpenClaw gateway is not ready')


def main() -> None:
    root = Path.cwd()
    environment = web_environment(dict(os.environ))
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment['PATH']
    try:
        ensure_gateway(root, environment)
    except Exception as error:
        print(f'[easel] 专用网关启动失败（{type(error).__name__}），请检查 /tmp/easel-gateway.log', file=sys.stderr)
        raise SystemExit(1)
    os.execve(str(root / '.venv/bin/easel'), ['easel', 'web', *sys.argv[1:]], environment)


if __name__ == '__main__':
    main()
