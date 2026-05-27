#!/usr/bin/env bash
# Usage: gpio-pulse <BCM_PIN> <DURATION_MS>
# Drives a GPIO pin high for DURATION_MS milliseconds, then drives it low.
# Uses pinctrl (not gpioset, which doesn't work on this hardware).
# Example: gpio-pulse 17 250   # pulse GPIO17 high for 250 ms

set -euo pipefail

PIN="${1:-}"
DURATION_MS="${2:-}"

if [[ -z "$PIN" || -z "$DURATION_MS" ]]; then
  echo "Usage: $(basename "$0") <BCM_PIN> <DURATION_MS>"
  exit 1
fi

if ! [[ "$DURATION_MS" =~ ^[0-9]+$ ]]; then
  echo "Error: DURATION_MS must be a positive integer."
  exit 1
fi

DURATION_S="$(awk "BEGIN { printf \"%.6f\", $DURATION_MS / 1000 }")"

pinctrl set "$PIN" dh
sleep "$DURATION_S"
pinctrl set "$PIN" dl
