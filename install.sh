#!/usr/bin/env bash
# Idempotent deployment helper for the attitude visualization demo.
# Creates/reuses .venv, verifies the I2C device and prints the access URL.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
PY="${PYTHON:-python3}"

echo "======================================================"
echo " IMU Visualization demo - install"
echo " Directory: ${PROJECT_DIR}"
echo "======================================================"

if ! command -v "${PY}" >/dev/null 2>&1; then
  echo "[ERROR] ${PY} not found. Install it with: sudo apt install python3" >&2
  exit 1
fi
echo "[1/4] Python: $(${PY} -V 2>&1)"

# Reuse .venv; rebuild only when the interpreter is actually broken.
if [ -d .venv ] && [ ! -x .venv/bin/python ]; then
  echo "[fix] .venv is incomplete; recreating it"
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  echo "[2/4] Creating .venv ..."
  if ! "${PY}" -m venv .venv; then
    echo "[WARN] python3-venv is unavailable; continuing with system Python"
    echo "       sudo apt install python3-venv, then rerun ./install.sh"
  fi
else
  echo "[2/4] Reusing existing .venv"
fi

PYEXE="${PY}"
if [ -x .venv/bin/python ]; then
  PYEXE=".venv/bin/python"
  # Self-heal: a renamed project directory leaves the old absolute path in
  # activate/pip shebangs, which makes the venv appear broken.
  if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    echo "[fix] .venv records an old path; repairing it"
    old_path="$(head -1 .venv/bin/pip 2>/dev/null | sed -n 's|^#!\(.*\)/bin/python.*|\1|p' || true)"
    if [ -n "${old_path}" ] && [ "${old_path}" != "${PROJECT_DIR}/.venv" ]; then
      for file in $(grep -rl -- "${old_path}" .venv/bin 2>/dev/null || true); do
        sed -i "s|${old_path}|${PROJECT_DIR}/.venv|g" "$file" || true
      done
      [ -f .venv/pyvenv.cfg ] && sed -i "s|${old_path}|${PROJECT_DIR}/.venv|g" .venv/pyvenv.cfg || true
    fi
  fi
  if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    echo "[WARN] .venv is unusable; continuing with system Python"
    PYEXE="${PY}"
  fi
fi

echo "[3/4] Installing dependencies (none required at runtime)"
if [ "${PYEXE}" != "${PY}" ] || [ -x .venv/bin/python ]; then
  "${PYEXE}" -m pip install -r requirements.txt >/dev/null 2>&1 || \
    echo "[WARN] pip install failed; the demo has no third-party runtime dependencies"
fi

chmod +x install.sh run.sh 2>/dev/null || true
chmod +x scripts/*.sh 2>/dev/null || true

echo "[4/4] Checking board interfaces"
if ls /dev/i2c-* >/dev/null 2>&1; then
  echo "  I2C buses: $(ls /dev/i2c-* | tr '\n' ' ')"
  if ! id -nG 2>/dev/null | tr ' ' '\n' | grep -qx i2c; then
    echo "  [warn] current user is not in the i2c group; run: sudo usermod -aG i2c \$USER"
  fi
  echo "  Probing MPU6050 ..."
  if ! PYTHONPATH=src "${PYEXE}" -m attitude.imu --probe; then
    echo "  [warn] MPU6050 not detected at 0x68/0x69."
    echo "         Check VCC/GND/SDA/SCL, then run: ./scripts/preflight.sh"
  fi
else
  echo "  [warn] /dev/i2c-* is missing; connect the MPU6050 before starting"
fi

if [ -f scripts/show_access_url.sh ] && [ -n "${HOME:-}" ]; then
  ln -sf "${PROJECT_DIR}/scripts/show_access_url.sh" "$HOME/imu-url" 2>/dev/null || true
  rm -f "$HOME/attitude-url" 2>/dev/null || true
  echo "  Shortcut: ~/imu-url -> scripts/show_access_url.sh"
fi

echo "======================================================"
echo "Installation complete"
echo "  Start : ./run.sh"
echo "  URL   : http://<board-ip>:8081/"
echo "======================================================"
