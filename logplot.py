#!/usr/bin/env python3
import re
import sys
import argparse
import matplotlib.pyplot as plt
from collections import deque

def moving_average(seq, window):
    """Simple causal moving average. window=1 -> no smoothing."""
    if window <= 1:
        return seq
    out = []
    q = deque()
    s = 0.0
    for v in seq:
        q.append(v)
        s += v
        if len(q) > window:
            s -= q.popleft()
        out.append(s / len(q))
    return out

# ---- Argument parsing ----
parser = argparse.ArgumentParser(
    description="Plot methane, windspeed, and current from a log file."
)
parser.add_argument("logfile", help="Path to the log file")
parser.add_argument(
    "--mhr",
    type=float,
    default=0.25,
    help="Methane Half-range around 2.0 that maps to ±10 for methane (default: 0.25, so 1.75→-10, 2.25→+10)",
)
parser.add_argument(
    "--maw",
    type=int,
    default=10,
    help="Moving average window in samples (default: 10; 1 disables smoothing)",
)

args = parser.parse_args()

log_path = args.logfile
methane_half_range = args.mhr
ma_window = args.maw

methane_vals = []
windspeed_vals = []
current_vals = []

pattern = re.compile(
    r"methane=([0-9.]+)\s+windspeed=([0-9.]+)\s+current=([0-9.]+)"
)

with open(log_path, "r") as f:
    for line in f:
        m = pattern.search(line)
        if not m:
            continue
        methane_vals.append(float(m.group(1)))
        windspeed_vals.append(float(m.group(2)))
        current_vals.append(float(m.group(3)))

if not methane_vals:
    print("No sensor lines found in log.")
    sys.exit(1)

# --- Scaling ---
# Methane: center at 2.0 and scale so (2.0 ± methane_half_range) -> ±10
methane_center = 2.0
methane_scale = 10.0 / methane_half_range
methane_scaled = [(v - methane_center) * methane_scale for v in methane_vals]

# Wind: fixed mapping 2.4 -> -10, 2.6 -> 0, 2.8 -> +10
wind_center = 2.6
wind_half_range = 0.2
wind_scale = 10.0 / wind_half_range
windspeed_scaled = [(v - wind_center) * wind_scale for v in windspeed_vals]

# Current: NOT scaled
current_unscaled = current_vals

# --- Moving average smoothing ---
methane_smoothed = moving_average(methane_scaled, ma_window)
windspeed_smoothed = moving_average(windspeed_scaled, ma_window)
current_smoothed = current_unscaled

x = range(len(methane_smoothed))  # sample index; ignoring actual time

plt.figure()
plt.plot(x, methane_smoothed, label="methane (scaled -10..+10, MA)")
plt.plot(x, windspeed_smoothed, label="windspeed (scaled -10..+10, MA)")
plt.plot(x, current_smoothed, label="current (raw)")

plt.xlabel("sample index")
plt.ylabel("value (scaled for methane/wind; raw for current)")
plt.title("Sensor readings from log")
plt.axhline(0.0, linestyle="--", linewidth=0.8)
plt.ylim(-10, 10)  # 0 in the center, full -10..+10 range

plt.legend()
plt.tight_layout()
plt.show()
