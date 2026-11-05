#!/usr/bin/env bash
# Compile the firmware in the ESPHome container and OTA-flash the device.
#
# usage: tools/flash.sh [--no-pull]
#
# Needs DEVICE_IP in .env (see DEVELOPING.md).
# Full build output goes to /tmp/flash.log; only a short
# summary is printed, so run this once in the background and wait for it to end
# rather than polling.
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
[ -f .env ] || { echo "missing .env (see DEVELOPING.md)"; exit 2; }
set -a; . ./.env; set +a
: "${DEVICE_IP:?set DEVICE_IP in .env}"

pull=1
for a in "$@"; do
  case "$a" in
    --no-pull) pull=0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done

log=/tmp/flash.log
start=$(date +%s)
[ "$pull" = 1 ] && docker pull -q ghcr.io/esphome/esphome:latest >/dev/null

if ! docker run --rm --net=host -v "$root/esphome":/config ghcr.io/esphome/esphome:latest \
    run m5stack-atom-echo.yaml --device "$DEVICE_IP" --no-logs >"$log" 2>&1; then
  echo "FAILED after $(( $(date +%s) - start ))s; last lines of $log:"
  tail -n 15 "$log"
  exit 1
fi
version=$(grep -o -m1 'ESPHome [0-9][0-9.a-z-]*' "$log" || true)
echo "flashed in $(( $(date +%s) - start ))s ${version}"
