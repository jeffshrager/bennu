#!/usr/bin/env bash
# Usage: gpio-hold-off <BCM_PIN> [gpiochip] [--drive-low]

set -euo pipefail
LINE="${1:-}"
CHIP="${2:-gpiochip0}"
EXTRA="${3:-}"

if [[ -z "$LINE" ]]; then
  echo "Usage: $(basename "$0") <BCM_PIN> [gpiochip] [--drive-low]"
  exit 1
fi

STATE_BASE="/run/gpiohold"
[[ -w "/run" ]] || STATE_BASE="/tmp/gpiohold"

PIDFILE="${STATE_BASE}/${CHIP}_${LINE}.pid"
META="${STATE_BASE}/${CHIP}_${LINE}.meta"

if [[ ! -f "$PIDFILE" ]]; then
  echo "No holder for ${CHIP}:${LINE}."
  exit 0
fi

PID="$(cat "$PIDFILE" || true)"
if [[ -n "$PID" && -d "/proc/$PID" ]]; then
  kill -INT "$PID" 2>/dev/null || true
  for i in {1..20}; do
    [[ ! -d "/proc/$PID" ]] && break
    sleep 0.05
  done
  [[ -d "/proc/$PID" ]] && kill -KILL "$PID" 2>/dev/null || true
  echo "Released holder for ${CHIP}:${LINE}."
else
  echo "Stale pidfile for ${CHIP}:${LINE}."
fi

# Log stop time (ISO 8601)
if [[ -f "$META" ]]; then
  echo "stopped=$(date --iso-8601=seconds)" >>"$META"
fi

if [[ -f "$META" ]]; then
  STOP_TIME=$(grep '^stopped=' "$META" | cut -d= -f2-)
  echo "GPIO ${CHIP}:${LINE} released at ${STOP_TIME}"
fi
echo "$(date --iso-8601=seconds) RELEASE ${CHIP}:${LINE}" >> "$HOME/gpio.log"

rm -f "$PIDFILE" "$META"

# Optional: actively pull low
if [[ "$EXTRA" == "--drive-low" ]]; then
  if command -v raspi-gpio >/dev/null 2>&1; then
    raspi-gpio set "$LINE" op dl
    echo "Drove ${CHIP}:${LINE} low and kept as output."
  else
    gpioset --mode=exit "$CHIP" "${LINE}=0"
    echo "Pulsed ${CHIP}:${LINE} low once (line released)."
  fi
fi
