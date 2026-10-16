#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [ -z "$LAN_IP" ]; then
  echo "未获取到局域网 IP，请检查网络连接。" >&2
  exit 1
fi
export EASEL_EXTRA_HOSTS="${EASEL_EXTRA_HOSTS:+$EASEL_EXTRA_HOSTS,}$LAN_IP"
export EASEL_EXTRA_ORIGINS="${EASEL_EXTRA_ORIGINS:+$EASEL_EXTRA_ORIGINS,}http://$LAN_IP:7860"
# Read only the public URL as data; never source .env as shell code.
PUBLIC_CONFIG="$(.venv/bin/python - <<'PYCONFIG'
from pathlib import Path
from urllib.parse import urlsplit
import re
from easel.direct_api import read_settings

value = read_settings(Path('.env')).get('EASEL_PUBLIC_URL', '').strip()
if value:
    try:
        url = urlsplit(value)
        valid = (url.scheme in {'http', 'https'} and url.hostname
                 and re.fullmatch(r'[A-Za-z0-9.:-]+', url.hostname)
                 and not url.username and not url.password
                 and url.path in {'', '/'} and not url.query and not url.fragment
                 and url.port != 0 and not any(c.isspace() or ord(c) < 32 for c in value)
                 and not any(c in value for c in ('\\', ',')))
    except ValueError:
        valid = False
    if not valid:
        raise SystemExit('EASEL_PUBLIC_URL 必须是完整的 http(s) 访问地址，可带端口，不含账号、路径或查询参数。')
    print(url.hostname)
    print(f'{url.scheme}://{url.netloc}')
PYCONFIG
)"
if [ -n "$PUBLIC_CONFIG" ]; then
  PUBLIC_HOST="${PUBLIC_CONFIG%%$'\n'*}"
  PUBLIC_ORIGIN="${PUBLIC_CONFIG#*$'\n'}"
  export EASEL_EXTRA_HOSTS="${EASEL_EXTRA_HOSTS:+$EASEL_EXTRA_HOSTS,}$PUBLIC_HOST"
  export EASEL_EXTRA_ORIGINS="${EASEL_EXTRA_ORIGINS:+$EASEL_EXTRA_ORIGINS,}$PUBLIC_ORIGIN"
  echo "Easel 反向代理访问地址：$PUBLIC_ORIGIN"
fi
echo "Easel 局域网地址：http://$LAN_IP:7860"
exec .venv/bin/easel web "$@"
