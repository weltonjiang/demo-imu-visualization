#!/usr/bin/env bash
# Print every LAN URL that can open the attitude UI.
set -euo pipefail

SELF="$(readlink -f "$0")"
cd "$(dirname "$SELF")/.."
PORT="${1:-8081}"
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

PYTHONPATH=src "$PY" - "$PORT" <<'PY'
import sys
from attitude.netinfo import access_urls, hostname

port = int(sys.argv[1])
urls = access_urls(port)
print(f"Host: {hostname()}")
if not urls:
    print(f"Open: http://127.0.0.1:{port}/")
else:
    for entry in urls:
        print(f"Open: {entry['url']}  ({entry['iface']})")
PY
