#!/usr/bin/env python3
"""
lamp_lag_scan.py
================
Scan for the sensor-response lag between a lamp ON/OFF event and its effect
showing up in the methane trace, for quad-log rigs (GPIO-driven
"bowport/bowstar/sternport/sternstar" quads; see lamp_analysis.py).

Rather than producing one report at lag=0 (the sensor reacts the instant the
lamps switch), this re-labels every sample using the quad state as of
(sample_time - lag) for a range of candidate lags, reruns the ON-vs-OFF
significance tests at each lag, and plots lag vs p-value. The lag with the
lowest p-value (strongest, most consistent ON/OFF separation) is the best
estimate of the true sensor-response delay.

Usage:
    python3 lamp_lag_scan.py <logfile> [-o lag_scan.png] [--max-lag 200] [--step 5]
"""
from __future__ import annotations
import argparse, sys
from datetime import timedelta
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lamp_analysis import (
    parse_log, parse_quad_events, lamp_state_from_quads,
    trim_to_experiment, correct_jumps, clean_windspeed,
    segment_cycles, per_cycle_effects, group_tests, paired_cycle_test,
)

_EMPTY_CYCLE_TEST = {
    "n_cycles": 0, "mean_effect": np.nan, "median_effect": np.nan,
    "sd_effect": np.nan, "ci95_low": np.nan, "ci95_high": np.nan,
    "t_stat": np.nan, "t_p": np.nan, "wilcoxon_W": np.nan, "wilcoxon_p": np.nan,
}


def lag_scan(df: pd.DataFrame, events: list, lags: list[int]) -> pd.DataFrame:
    """
    For each candidate lag (seconds), relabel df['lamp'] using the quad
    state as of (sample_time - lag), drop ramp samples, and rerun the
    ON-vs-OFF tests. Returns one row per lag.
    """
    rows = []
    for lag in lags:
        shifted = [(t + timedelta(seconds=lag), name, on) for t, name, on in events]
        lamp, _ = lamp_state_from_quads(df["time"], shifted)
        sub = df.copy()
        sub["lamp"] = lamp
        sub = sub.loc[sub["lamp"] != -1].reset_index(drop=True)

        row = {"lag": lag, "n": len(sub)}
        if sub["lamp"].nunique() < 2 or len(sub) < 50:
            rows.append(row)
            continue

        group = group_tests(sub)
        cycles = segment_cycles(sub)
        effects = per_cycle_effects(cycles)
        ct = paired_cycle_test(effects) if len(effects) else _EMPTY_CYCLE_TEST

        row.update({
            "n_on_cycles": sum(1 for c in cycles if c.state == 1),
            "welch_diff": group["diff"],
            "welch_p": group["welch_p"],
            "mannwhitney_p": group["mannwhitney_p"],
            "paired_n_cycles": ct["n_cycles"],
            "paired_mean_effect": ct["mean_effect"],
            "paired_ci95_low": ct["ci95_low"],
            "paired_ci95_high": ct["ci95_high"],
            "paired_t_p": ct["t_p"],
            "wilcoxon_p": ct["wilcoxon_p"],
        })
        rows.append(row)
    return pd.DataFrame(rows)


def make_plot(results: pd.DataFrame, out_png: str):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    for col, label, marker in [
        ("welch_p", "Welch t (sample-level ON vs OFF)", "o"),
        ("paired_t_p", "paired t (cycle-paired effect)", "s"),
        ("wilcoxon_p", "Wilcoxon signed-rank (cycle-paired)", "^"),
    ]:
        y = -np.log10(results[col].astype(float))
        ax1.plot(results["lag"], y, marker=marker, ms=4, lw=1, label=label)
    ax1.axhline(-np.log10(0.05), color="red", ls="--", lw=1, label="p = 0.05")
    ax1.set_ylabel("-log10(p)")
    ax1.set_title("Significance of ON vs OFF methane effect, by assumed sensor-response lag")
    ax1.legend(fontsize=8, loc="best")

    e = results["paired_mean_effect"].astype(float)
    lo = results["paired_ci95_low"].astype(float)
    hi = results["paired_ci95_high"].astype(float)
    ax2.plot(results["lag"], e, color="black", lw=1, marker="o", ms=3)
    ax2.fill_between(results["lag"], lo, hi, alpha=0.2, color="black")
    ax2.axhline(0, color="grey", lw=0.8)
    ax2.set_ylabel("cycle-paired ON effect (ppm)")
    ax2.set_xlabel("assumed lag (s)")

    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile", nargs="+",
                    help="one or more quad-log lamp_controller.log files")
    ap.add_argument("-o", "--out", default="lamp_lag_scan.png")
    ap.add_argument("--csv", default=None, help="also write per-lag results to this CSV path")
    ap.add_argument("--max-lag", type=int, default=200,
                    help="largest lag to test, in seconds (default 200)")
    ap.add_argument("--step", type=int, default=5,
                    help="lag step size, in seconds (default 5, matching the sample rate)")
    ap.add_argument("--jump-k", type=float, default=8.0,
                    help="Jump-detection threshold in MAD-scaled sigmas (default 8)")
    args = ap.parse_args()

    df = parse_log(args.logfile)
    if len(df) < 100:
        sys.exit(f"Too few valid samples parsed ({len(df)}).")

    events = parse_quad_events(args.logfile)
    if not events:
        sys.exit("No 'Quad ... set to ON/OFF' events found; this tool requires a "
                  "quad-log rig (see lamp_analysis.py).")

    lamp0, _ = lamp_state_from_quads(df["time"], events)
    df["lamp"] = lamp0
    df, n_trimmed = trim_to_experiment(df)
    if len(df) < 100:
        sys.exit(f"Too few samples after trim ({len(df)}).")

    df["methane_corr"], jumps = correct_jumps(df["methane"].values, k=args.jump_k)
    df["windspeed"], n_wind_faults = clean_windspeed(df["windspeed"].values)

    lags = list(range(0, args.max_lag + 1, args.step))
    results = lag_scan(df, events, lags)

    if args.csv:
        results.to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")

    make_plot(results, args.out)
    print(f"Wrote {args.out}  ({len(df)} samples, {n_trimmed} trimmed, "
          f"{len(jumps)} jumps corrected, {n_wind_faults} wind faults interpolated, "
          f"{len(lags)} lags tested from 0 to {args.max_lag}s)")

    valid = results.dropna(subset=["paired_t_p"])
    if len(valid):
        best = valid.loc[valid["paired_t_p"].idxmin()]
        print(f"Best lag by cycle-paired t-test: {int(best['lag'])}s "
              f"(p={best['paired_t_p']:.4g}, mean effect={best['paired_mean_effect']:+.4f} ppm, "
              f"n_cycles={int(best['paired_n_cycles'])})")
    valid_w = results.dropna(subset=["welch_p"])
    if len(valid_w):
        best_w = valid_w.loc[valid_w["welch_p"].idxmin()]
        print(f"Best lag by sample-level Welch t-test: {int(best_w['lag'])}s "
              f"(p={best_w['welch_p']:.4g}, diff={best_w['welch_diff']:+.4f} ppm)")


if __name__ == "__main__":
    main()
