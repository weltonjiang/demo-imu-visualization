#!/usr/bin/env bash
# Start the IMU visualization web UI.
#   ./run.sh                 use the MPU6050 on I2C (HTTP port 8081)
#   ./run.sh --port 9000     override the HTTP port
#
# If the file has no execute bit (copied from Windows), use: bash run.sh
set -euo pipefail

cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1

PY=""
for candidate in .venv/bin/python .venv/bin/python3; do
  if [ -x "$candidate" ]; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
  else
    echo "[ERROR] Python 3 not found. Run ./install.sh first." >&2
    exit 1
  fi
fi

exec "$PY" src/main.py "$@"
