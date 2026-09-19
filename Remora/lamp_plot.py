#!/usr/bin/env python3
"""
lamp_plot.py
============
Interactive plot of a lamp-controller sensor log, read from a .tar.gz of
logs (same input and same cleaning as lamp_analysis.py).

Top panel: drift-corrected methane, shaded yellow while the lamp is ON and
blue while OFF. Bottom panel: windspeed. Both share the time axis.

Navigation:
    toolbar zoom/pan      as usual
    mouse wheel           zoom time axis around the cursor
    left / right arrows   scroll time axis by a quarter of the visible span
    home (h)              reset view

Usage:
    python3 lamp_plot.py <logs.tar.gz>
"""
import argparse, os, tempfile
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch

from lamp_analysis import extract_logs, prepare

ON_COLOR, OFF_COLOR = "#FFF3A0", "#B8DDF5"


def break_gaps(t, *ys):
    """Insert NaNs at large time gaps (between days) so lines don't bridge them."""
    tn = mdates.date2num(t)
    dt = np.diff(tn)
    gaps = np.flatnonzero(dt > 10 * np.median(dt)) + 1
    if len(gaps) == 0:
        return (tn,) + tuple(np.asarray(y, dtype=float) for y in ys)
    out = [np.insert(tn, gaps, tn[gaps - 1] + np.median(dt))]
    for y in ys:
        out.append(np.insert(np.asarray(y, dtype=float), gaps, np.nan))
    return tuple(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tarball", help="a .tar.gz containing the log files")
    ap.add_argument("--jump-k", type=float, default=8.0)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        df = prepare(extract_logs(args.tarball, tmp), args.jump_k)[0]

    t = df["time"]
    x, methane, wind = break_gaps(t, df["methane_corr"], df["windspeed"])
    tn = mdates.date2num(t)

    fig, (ax, axw) = plt.subplots(2, 1, sharex=True, figsize=(14, 7),
                                  gridspec_kw={"height_ratios": [3, 1]})
    lamp = df["lamp"].values == 1
    for a in (ax, axw):
        trans = a.get_xaxis_transform()
        a.fill_between(tn, 0, 1, where=lamp, step="post", transform=trans,
                       facecolor=ON_COLOR, alpha=0.85, zorder=0, lw=0)
        a.fill_between(tn, 0, 1, where=~lamp, step="post", transform=trans,
                       facecolor=OFF_COLOR, alpha=0.85, zorder=0, lw=0)

    ax.plot(x, methane, color="black", lw=0.7, zorder=3)
    ax.axhline(np.nanmean(methane), color="red", ls="--", lw=1, zorder=4)
    ax.set_ylabel("Methane (ppm)")
    ax.set_title(f"{os.path.basename(args.tarball)} — methane, lamp ON (yellow) vs OFF (blue)")
    ax.legend(handles=[Patch(facecolor=ON_COLOR, edgecolor="k", label="ON"),
                       Patch(facecolor=OFF_COLOR, edgecolor="k", label="OFF"),
                       plt.Line2D([0], [0], color="red", ls="--", label="overall mean")],
              loc="upper left", framealpha=0.9)

    axw.plot(x, wind, color="#4E8C6E", lw=0.7, zorder=3)
    axw.set_ylabel("Windspeed")
    loc = mdates.AutoDateLocator()
    axw.xaxis.set_major_locator(loc)
    axw.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))

    # fill_between's 0..1 axes-fraction spans would otherwise drag the data
    # limits to include 0, so set the y ranges from the data explicitly.
    for a, y in ((ax, methane), (axw, wind)):
        lo, hi = np.nanmin(y), np.nanmax(y)
        pad = 0.05 * (hi - lo) or 0.5
        a.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(tn[0], tn[-1])
    home = ax.get_xlim()

    def on_scroll(ev):
        if ev.inaxes not in (ax, axw) or ev.xdata is None:
            return
        f = 0.8 if ev.button == "up" else 1.25
        lo, hi = ax.get_xlim()
        ax.set_xlim(ev.xdata - (ev.xdata - lo) * f, ev.xdata + (hi - ev.xdata) * f)
        fig.canvas.draw_idle()

    def on_key(ev):
        lo, hi = ax.get_xlim()
        if ev.key in ("left", "right"):
            d = (hi - lo) / 4 * (-1 if ev.key == "left" else 1)
            ax.set_xlim(lo + d, hi + d)
        elif ev.key in ("h", "home"):
            ax.set_xlim(*home)
        else:
            return
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("scroll_event", on_scroll)
    fig.canvas.mpl_connect("key_press_event", on_key)
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
