#!/usr/bin/env python3
"""
lamp_ramp_plot.py
==================
Overlay of the lamp ramp transients -- the samples lamp_analysis.py and
lamp_plot.py exclude from the ON/OFF comparison because only *some* quads
are energized (the sequential ramp-up/ramp-down). Quad-log rigs only; a
current-sensor rig switches instantly and has no ramp state to overlay.

Each ramp instance is anchored at its own start time (relative seconds)
and, for methane, baseline-subtracted against its own pre-ramp value, then
all instances are overlaid on one axis. The mean across instances is drawn
with standard-error bars. A second panel overlays the physical ramp
profile itself (fraction of quads energized) the same way, as a sanity
check that the instances line up.

Usage:
    python3 lamp_ramp_plot.py <logs.tar.gz> [-o out.png]
                               [--direction up|down|both] [--jump-k K]
"""
import argparse, os, sys, tempfile
import numpy as np
import matplotlib.pyplot as plt

from lamp_analysis import (
    extract_logs, parse_log, parse_quad_events, quad_on_counts, correct_jumps,
)

SAMPLE_STEP = 5.0  # seconds; nominal sensor sample interval


def find_ramp_blocks(lamp: np.ndarray, direction: str) -> list[tuple[int, int]]:
    """
    Contiguous runs of lamp == -1 (ramp), paired with the bracketing
    OFF/ON sample on each side and filtered to `direction`
    ('up': OFF->ON, 'down': ON->OFF, 'both': either). A run bracketed by
    the same state on both sides (a flicker that didn't complete) matches
    neither and is dropped.

    Returns (start, end) sample-index pairs, INCLUSIVE of the bracketing
    sample at each end, so the overlay shows the settle at both ends.
    """
    is_ramp = lamp == -1
    edges = np.flatnonzero(np.diff(is_ramp.astype(int)) != 0) + 1
    bounds = np.r_[0, edges, len(lamp)]
    blocks = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if not is_ramp[a] or a == 0 or b >= len(lamp):
            continue
        before, after = lamp[a - 1], lamp[b]
        if direction == "up" and not (before == 0 and after == 1):
            continue
        if direction == "down" and not (before == 1 and after == 0):
            continue
        if direction == "both" and before == after:
            continue
        blocks.append((a - 1, b))
    return blocks


def overlay(tn: np.ndarray, series: np.ndarray, blocks: list[tuple[int, int]],
            baseline_subtract: bool):
    """
    Put each ramp instance on a common relative-time-from-start grid via
    linear interpolation (baseline-subtracted against its own first
    sample, if requested). Returns (grid, matrix); matrix is
    n_instances x len(grid), NaN past an instance's own duration.
    """
    durations = [tn[b] - tn[a] for a, b in blocks]
    grid = np.arange(0, max(durations) + SAMPLE_STEP, SAMPLE_STEP)
    mat = np.full((len(blocks), len(grid)), np.nan)
    for row, (a, b) in enumerate(blocks):
        t_rel = tn[a:b + 1] - tn[a]
        y = series[a:b + 1] - (series[a] if baseline_subtract else 0.0)
        n = int(np.floor(t_rel[-1] / SAMPLE_STEP)) + 1
        mat[row, :n] = np.interp(grid[:n], t_rel, y)
    return grid, mat


def mean_sem(mat: np.ndarray):
    """Per-column mean, SEM (NaN where <2 instances cover that point), and coverage count."""
    n = np.sum(np.isfinite(mat), axis=0)
    mean = np.full(mat.shape[1], np.nan)
    sem = np.full(mat.shape[1], np.nan)
    have = n > 0
    mean[have] = np.nanmean(mat[:, have], axis=0)
    multi = n > 1
    if np.any(multi):
        sd = np.nanstd(mat[:, multi], axis=0, ddof=1)
        sem[multi] = sd / np.sqrt(n[multi])
    return mean, sem, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tarball", help="a .tar.gz containing the log files")
    ap.add_argument("-o", "--out",
                    help="save a PNG instead of opening an interactive window")
    ap.add_argument("--jump-k", type=float, default=8.0)
    ap.add_argument("--direction", choices=["up", "down", "both"], default="up",
                    help="which ramp transitions to overlay "
                         "(default: up, i.e. lamps turning on)")
    ap.add_argument("--err-points", type=int, default=15,
                    help="number of error-bar markers drawn along the mean "
                         "curve (default 15)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        paths = extract_logs(args.tarball, tmp)
        df = parse_log(paths)
        events = parse_quad_events(paths)
    if not events:
        sys.exit("No 'Quad ... set to ON/OFF' events found -- this rig has no "
                  "ramp state to overlay (current-sensor rigs switch instantly).")

    counts, n_quads = quad_on_counts(df["time"], events)
    lamp = np.where(counts == n_quads, 1, np.where(counts == 0, 0, -1))
    methane_corr, _ = correct_jumps(df["methane"].values, k=args.jump_k)
    frac_on = counts / n_quads
    tn = (df["time"] - df["time"].iloc[0]).dt.total_seconds().values

    blocks = find_ramp_blocks(lamp, args.direction)
    if len(blocks) < 2:
        sys.exit(f"Only {len(blocks)} ramp-{args.direction} instance(s) found; "
                  f"need at least 2 to overlay with error bars.")
    durations = [tn[b] - tn[a] for a, b in blocks]

    grid, mat_m = overlay(tn, methane_corr, blocks, baseline_subtract=True)
    _,    mat_f = overlay(tn, frac_on,       blocks, baseline_subtract=False)
    mean_m, sem_m, n_cov = mean_sem(mat_m)

    # Truncate the tail where fewer than 2 instances still cover the grid
    # (the longest instance(s) alone past that point, noisy and not really
    # an "overlay" any more).
    covered = np.flatnonzero(n_cov >= 2)
    last = int(covered[-1]) if len(covered) else 0
    grid, mat_m, mat_f = grid[:last + 1], mat_m[:, :last + 1], mat_f[:, :last + 1]
    mean_m, sem_m, n_cov = mean_m[:last + 1], sem_m[:last + 1], n_cov[:last + 1]
    mean_f, sem_f, _ = mean_sem(mat_f)

    dirn = {"up": "turning ON", "down": "turning OFF", "both": "turning ON/OFF"}[args.direction]
    print(f"{len(blocks)} ramp-{args.direction} instance(s) ({dirn}), "
          f"median duration {np.median(durations):.0f}s")

    fig, (ax, axf) = plt.subplots(2, 1, sharex=True, figsize=(9, 7))
    err_idx = np.unique(np.linspace(0, len(grid) - 1,
                                    min(args.err_points, len(grid))).astype(int))

    for row in range(mat_m.shape[0]):
        ax.plot(grid, mat_m[row], color="0.75", lw=0.6, zorder=1)
    ax.plot(grid, mean_m, color="black", lw=1.6, zorder=3, label=f"mean (n={len(blocks)})")
    ax.errorbar(grid[err_idx], mean_m[err_idx], yerr=sem_m[err_idx], fmt="none",
               ecolor="crimson", elinewidth=1.2, capsize=3, zorder=4, label="± SEM")
    ax.axhline(0, color="gray", lw=0.6, ls=":")
    ax.set_ylabel("Δ methane (ppm, rel. to ramp start)")
    ax.set_title(f"{os.path.basename(args.tarball)} — {len(blocks)} ramp instances ({dirn})")
    ax.legend(loc="upper left", framealpha=0.9)

    for row in range(mat_f.shape[0]):
        axf.plot(grid, mat_f[row], color="0.75", lw=0.6, zorder=1)
    axf.plot(grid, mean_f, color="#2A6F97", lw=1.6, zorder=3)
    axf.errorbar(grid[err_idx], mean_f[err_idx], yerr=sem_f[err_idx], fmt="none",
                ecolor="crimson", elinewidth=1.2, capsize=3, zorder=4)
    axf.set_ylabel("quads on / total")
    axf.set_xlabel("seconds from ramp start")
    axf.set_ylim(-0.05, 1.05)

    fig.tight_layout()
    if args.out:
        fig.savefig(args.out, dpi=160)
        print(f"Wrote {args.out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
