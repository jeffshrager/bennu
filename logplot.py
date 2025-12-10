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


def main():
    # ---- Argument parsing ----
    parser = argparse.ArgumentParser(
        description="Plot methane, windspeed, and current from a log file."
    )
    parser.add_argument("logfile", help="Path to the log file")

    # Keep --mhr for backward compatibility, but it's no longer used
    parser.add_argument(
        "--mhr",
        type=float,
        default=0.25,
        help="(Unused) legacy methane half-range argument; kept for compatibility.",
    )
    parser.add_argument(
        "--maw",
        type=int,
        default=10,
        help=(
            "Moving average window in samples for methane/wind "
            "(default: 10; 1 disables smoothing)"
        ),
    )

    args = parser.parse_args()

    log_path = args.logfile
    ma_window = args.maw

    methane_vals = []
    windspeed_vals = []
    current_vals = []

    # Adjust this regex if your log line format changes.
    # It expects lines like:
    #   ... methane=2.03 ... windspeed=2.51 ... current=0.12 ...
    pattern = re.compile(
        r"methane=([0-9.]+).*windspeed=([0-9.]+).*current=([0-9.]+)"
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

    # --- Moving average smoothing ---
    methane_smoothed = moving_average(methane_vals, ma_window)
    windspeed_smoothed = moving_average(windspeed_vals, ma_window)
    current_series = current_vals  # no smoothing for current

    x = range(len(methane_smoothed))  # sample index; ignoring actual time

    # --- Y ranges from raw data mins/maxes ---
    def min_max(seq):
        lo = min(seq)
        hi = max(seq)
        if lo == hi:
            # Avoid zero-height axis; pad a bit
            pad = 0.1 * (abs(lo) if lo != 0 else 1.0)
            return lo - pad, hi + pad
        return lo, hi

    # Use smoothed series for y-limits of methane and wind,
    # raw for current (since that's what we plot).
    methane_lo, methane_hi = min_max(methane_smoothed)
    wind_lo, wind_hi = min_max(windspeed_smoothed)
    current_lo, current_hi = min_max(current_vals)

    # --- Plotting: 3 aligned subplots (methane / current / wind) ---
    fig, (ax_methane, ax_current, ax_wind) = plt.subplots(
        3, 1, sharex=True, figsize=(10, 8),
        gridspec_kw={"height_ratios": [5, 1, 5]},  # methane, current, wind
    )

    # Top: methane (smoothed)
    ax_methane.plot(x, methane_smoothed, label=f"methane (MA window={ma_window})", color="tab:red")
    ax_methane.set_ylabel("methane")
    ax_methane.set_ylim(methane_lo, methane_hi)
    ax_methane.legend(loc="upper right")

    # Middle: current (raw)
    ax_current.plot(x, current_series, label="current (raw)", color="tab:blue")
    ax_current.set_ylabel("current")
    ax_current.set_ylim(current_lo, current_hi)
    ax_current.legend(loc="upper right")

    # Bottom: windspeed (smoothed)
    ax_wind.plot(x, windspeed_smoothed, label=f"windspeed (MA window={ma_window})", color="tab:green")
    ax_wind.set_ylabel("windspeed")
    ax_wind.set_xlabel("sample index")
    ax_wind.set_ylim(wind_lo, wind_hi)
    ax_wind.legend(loc="upper right")

    fig.suptitle("Sensor readings from log")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
