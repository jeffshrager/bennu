#!/usr/bin/env bash
# Usage: gpio-hold-status [--hardware]
# Lists all known held pins and their ISO timestamps.

set -euo pipefail
SHOW_HW=false
[[ "${1:-}" == "--hardware" ]] && SHOW_HW=true

STATE_BASE="/run/gpiohold"
[[ -w "/run" ]] || STATE_BASE="/tmp/gpiohold"
[[ -d "$STATE_BASE" ]] || { echo "No holds recorded."; exit 0; }

shopt -s nullglob
METAFILES=("$STATE_BASE"/*.meta)
(( ${#METAFILES[@]} == 0 )) && { echo "No pins held."; exit 0; }

printf "%-10s %-6s %-6s %-8s %-10s %-35s" "CHIP" "LINE" "VALUE" "PID" "STATUS" "TIME"
$SHOW_HW && printf "  %-24s" "HARDWARE"
printf "\n"

for META in "${METAFILES[@]}"; do
  CHIP_LINE="$(basename "$META" .meta)"
  CHIP="${CHIP_LINE%_*}"
  LINE="${CHIP_LINE##*_}"

  PIDFILE="${STATE_BASE}/${CHIP}_${LINE}.pid"
  PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  START="$(grep '^started=' "$META" | cut -d= -f2- || true)"
  STOP="$(grep '^stopped=' "$META" | cut -d= -f2- || true)"
  VAL="$(grep '^value=' "$META" | cut -d= -f2- || echo '?')"

  if [[ -n "$PID" && -d "/proc/$PID" ]]; then
    STATUS="alive"
  else
    STATUS="stopped"
    rm -f "$PIDFILE" 2>/dev/null || true
  fi

  TIME="$START"
  [[ -n "$STOP" ]] && TIME="${START} → ${STOP}"

  printf "%-10s %-6s %-6s %-8s %-10s %-35s" "$CHIP" "$LINE" "$VAL" "${PID:-"-"}" "$STATUS" "$TIME"

  if $SHOW_HW; then
    if command -v raspi-gpio >/dev/null 2>&1; then
      HW="$(raspi-gpio get "$LINE" 2>/dev/null | tr -s ' ')"
      printf "  %-24s" "$HW"
    else
      printf "  %-24s" "(no raspi-gpio)"
    fi
  fi

  printf "\n"
done
