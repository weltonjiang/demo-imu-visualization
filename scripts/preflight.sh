#!/usr/bin/env bash
# Read-only checks before starting the hardware demo.
set -euo pipefail

cd "$(dirname "$0")/.."
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

echo "== Python =="
"$PY" -V
echo "== Modules =="
PYTHONPATH=src "$PY" - <<'PY'
from attitude import VERSION
from attitude.imu import available_buses

print(f"attitude package : {VERSION}")
print(f"I2C buses        : {available_buses() or 'none'}")
PY

echo "== I2C / MPU6050 =="
if ls /dev/i2c-* >/dev/null 2>&1; then
  PYTHONPATH=src "$PY" -m attitude.imu --probe || true
else
  echo "no /dev/i2c-* device; connect the MPU6050 before starting"
fi

echo "== Access URLs =="
PORT="${1:-8081}"
if [ -x .venv/bin/python ]; then
  ./scripts/show_access_url.sh "$PORT"
else
  PYTHONPATH=src python3 - "$PORT" <<'PY'
import sys
from attitude.netinfo import access_urls
for entry in access_urls(int(sys.argv[1])):
    print(f"Open: {entry['url']}")
PY
fi
