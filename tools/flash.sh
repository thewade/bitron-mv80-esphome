#!/usr/bin/env bash
# Compile the firmware in the ESPHome container, OTA-flash the device, then
# (optionally) switch Audio Capture back on, since a reboot turns it off.
#
# usage: tools/flash.sh [--no-capture] [--no-pull]
#
# Needs DEVICE_IP in .env (see .env.example). Re-enabling capture also needs
# HA_URL and HA_TOKEN. Full build output goes to /tmp/flash.log; only a short
# summary is printed, so run this once in the background and wait for it to end
# rather than polling.
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
[ -f .env ] || { echo "missing .env (copy .env.example)"; exit 2; }
set -a; . ./.env; set +a
: "${DEVICE_IP:?set DEVICE_IP in .env}"

capture=1; pull=1
for a in "$@"; do
  case "$a" in
    --no-capture) capture=0 ;;
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

if [ "$capture" = 1 ] && [ -n "${HA_URL:-}" ] && [ -n "${HA_TOKEN:-}" ]; then
  sw=switch.entryway_m5stack_atom_echo_audio_capture
  state=unknown
  sleep 25  # device reboots and reconnects to Home Assistant
  for _ in 1 2 3 4; do
    curl -s -m 8 -X POST -H "Authorization: Bearer $HA_TOKEN" -H 'Content-Type: application/json' \
      -d "{\"entity_id\":\"$sw\"}" "$HA_URL/api/services/switch/turn_on" >/dev/null
    sleep 5
    state=$(curl -s -m 8 -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states/$sw" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("state","unknown"))' 2>/dev/null || echo unknown)
    [ "$state" = on ] && break
  done
  echo "audio capture switch: $state"
fi
