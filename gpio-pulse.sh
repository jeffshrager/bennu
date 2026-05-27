#!/usr/bin/env bash
# Usage: gpio-pulse <BCM_PIN> <DURATION_MS> [gpiochip] [value]
# Drives a GPIO pin to VALUE for DURATION_MS milliseconds, then releases it.
# Example: gpio-pulse 17 250          # pulse GPIO17 high for 250 ms
#          gpio-pulse 17 500 gpiochip0 0  # pulse GPIO17 low for 500 ms

set -euo pipefail

LINE="${1:-}"
DURATION_MS="${2:-}"
CHIP="${3:-gpiochip0}"
VAL="${4:-1}"

if [[ -z "$LINE" || -z "$DURATION_MS" ]]; then
  echo "Usage: $(basename "$0") <BCM_PIN> <DURATION_MS> [gpiochip] [value]"
  exit 1
fi

if ! [[ "$DURATION_MS" =~ ^[0-9]+$ ]]; then
  echo "Error: DURATION_MS must be a positive integer."
  exit 1
fi

DURATION_S="$(awk "BEGIN { printf \"%.6f\", $DURATION_MS / 1000 }")"

gpioset --mode=time --sec=0 --usec="$(( DURATION_MS * 1000 ))" "$CHIP" "${LINE}=${VAL}"
