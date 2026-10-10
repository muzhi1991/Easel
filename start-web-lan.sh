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
# Trust exact origins of saved API providers for proxy Fake-IP DNS.
# A native primary (e.g. Codex) has no URL; backup providers still need discovery.
if [ -z "${EASEL_FAKE_IP_ORIGINS:-}" ]; then
  EASEL_FAKE_IP_ORIGINS="$(.venv/bin/python - <<'PYCONFIG'
import json
from urllib.parse import urlsplit
from easel.openclaw_workspace import config_path
config = json.loads(config_path().read_text())
origins = set()
for provider in config.get('models', {}).get('providers', {}).values():
    url = urlsplit(provider.get('baseUrl', ''))
    if url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password:
        origins.add(f'{url.scheme}://{url.netloc}')
print(','.join(sorted(origins)))
PYCONFIG
)"
fi
export EASEL_FAKE_IP_ORIGINS
echo "Easel 局域网地址：http://$LAN_IP:7860"
exec .venv/bin/easel web "$@"
