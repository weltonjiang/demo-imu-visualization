#!/usr/bin/env bash
# Open the UI in Chromium kiosk mode (touchscreen).
#   ./scripts/start_kiosk.sh                 -> http://127.0.0.1:8081/
#   ./scripts/start_kiosk.sh http://...       -> custom URL
set -euo pipefail

URL="${1:-http://127.0.0.1:8081/}"
BROWSER=""
for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$BROWSER" ]; then
  echo "[ERROR] Chromium was not found. Install it with: sudo apt install chromium" >&2
  exit 1
fi

exec "$BROWSER" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=Translate,MediaRouter \
  --autoplay-policy=no-user-gesture-required \
  "$URL"
