#!/usr/bin/env bash
# Usage: gpio-hold-on <BCM_PIN> [gpiochip] [value]
# Example: gpio-hold-on 17            # hold GPIO17 high
#          gpio-hold-on 17 gpiochip0 0 # hold GPIO17 low

set -euo pipefail
LINE="${1:-}"
CHIP="${2:-gpiochip0}"
VAL="${3:-1}"

if [[ -z "$LINE" ]]; then
  echo "Usage: $(basename "$0") <BCM_PIN> [gpiochip] [value]"
  exit 1
fi

STATE_BASE="/run/gpiohold"
[[ -w "/run" ]] || STATE_BASE="/tmp/gpiohold"
mkdir -p "$STATE_BASE"

PIDFILE="${STATE_BASE}/${CHIP}_${LINE}.pid"
META="${STATE_BASE}/${CHIP}_${LINE}.meta"

# Prevent duplicates
if [[ -f "$PIDFILE" ]]; then
  OLD_PID="$(cat "$PIDFILE" || true)"
  if [[ -n "$OLD_PID" && -d "/proc/$OLD_PID" ]]; then
    echo "GPIO ${LINE} on ${CHIP} already held by PID $OLD_PID."
    exit 0
  else
    rm -f "$PIDFILE" "$META"
  fi
fi

nohup gpioset --mode=wait "$CHIP" "${LINE}=${VAL}" >> "$STATE_BASE/${CHIP}_${LINE}.log" 2>&1 &
PID=$!

# Record metadata with ISO 8601 timestamp (local time zone)
{
  echo "started=$(date --iso-8601=seconds)"
  echo "pid=$PID"
  echo "chip=$CHIP"
  echo "line=$LINE"
  echo "value=$VAL"
} >"$META"

echo "$PID" >"$PIDFILE"

sleep 0.2
for i in {1..5}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Failed to start holder for ${CHIP}:${LINE}."
    cat "$STATE_BASE/${CHIP}_${LINE}.log" 2>/dev/null
    rm -f "$PIDFILE" "$META"
    exit 2
  fi
  sleep 0.1
done

echo "Holding ${CHIP}:${LINE}=${VAL} (PID $PID) since $(grep '^started=' "$META" | cut -d= -f2-)"
echo "$(date --iso-8601=seconds) HOLD ${CHIP}:${LINE}=${VAL} PID=$PID" >> "$HOME/gpio.log"
