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
# Trust only the configured primary provider's origin for proxy Fake-IP DNS.
if [ -z "${EASEL_FAKE_IP_ORIGINS:-}" ]; then
  EASEL_FAKE_IP_ORIGINS="$(.venv/bin/python - <<'PYCONFIG'
import json
from pathlib import Path
from urllib.parse import urlsplit
config = json.loads((Path.home() / '.openclaw-easel/openclaw.json').read_text())
provider = config['agents']['defaults']['model']['primary'].split('/', 1)[0]
url = urlsplit(config['models']['providers'][provider]['baseUrl'])
print(f'{url.scheme}://{url.netloc}')
PYCONFIG
)"
fi
export EASEL_FAKE_IP_ORIGINS
echo "Easel 局域网地址：http://$LAN_IP:7860"
exec .venv/bin/easel web "$@"
