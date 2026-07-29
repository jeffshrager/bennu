#!/usr/bin/env python3
"""
lamp_analysis.py
================
Statistical analysis of a lamp-controller sensor log (methane, windspeed,
current) and generation of a PDF report.

Input log lines (one per 5-s sample) look like:
    2026-05-02T17:18:54-0700 [INFO] Sensors: time=... methane=1.849 windspeed=4.09 current=0.325
    2026-05-02T17:19:24-0700 [ERROR] Error reading methane sensor: ...

Lamp state is inferred from the driver current (bimodal: ~0.325 A OFF,
~0.60 A ON). Baseline step-jumps in the methane trace (sensor
recalibration ticks, unrelated to the lamp cycle) are detected and removed.

Usage:
    python3 lamp_analysis.py <logfile> [-o report.pdf]
"""
from __future__ import annotations
import argparse, re, sys, io
from datetime import datetime
from dataclasses import dataclass
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from scipy import stats
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)


# ---------------------------------------------------------------------------
# 1. PARSING
# ---------------------------------------------------------------------------
LINE_RE = re.compile(
    r"time=(?P<t>\S+)\s+methane=(?P<m>[\w.\-]+)\s+"
    r"windspeed=(?P<w>[\w.\-]+)\s+current=(?P<c>[\w.\-]+)"
)


def parse_log(paths: list[str]) -> pd.DataFrame:
    """Parse one or more log files, concatenate, sort by time, dedupe."""
    rows = []
    for path in paths:
        with open(path) as fh:
            for line in fh:
                if "Sensors:" not in line:
                    continue
                m = LINE_RE.search(line)
                if not m:
                    continue
                def _f(x):
                    try: return float(x)
                    except ValueError: return np.nan
                rows.append((
                    datetime.fromisoformat(m["t"]),
                    _f(m["m"]), _f(m["w"]), _f(m["c"]),
                ))
    df = pd.DataFrame(rows, columns=["time", "methane", "windspeed", "current"])
    df = df.dropna(subset=["methane", "current"])
    df = df.sort_values("time").drop_duplicates(subset="time", keep="first")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. LAMP STATE
# ---------------------------------------------------------------------------
def trim_to_experiment(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Drop the pre-cycling period. The experiment is defined as starting at
    the first OFF→ON transition. Returns the trimmed frame and the number
    of samples dropped.
    """
    lamp = df["lamp"].values
    on_idx = np.flatnonzero(lamp == 1)
    if len(on_idx) == 0:
        return df, 0
    first_on = int(on_idx[0])
    if first_on == 0:
        return df, 0
    return df.iloc[first_on:].reset_index(drop=True), first_on


def clean_windspeed(w: np.ndarray) -> tuple[np.ndarray, int]:
    """
    The wind sensor normally operates in a narrow band; the meaningful
    signal lives in the last few decimal digits. Occasional reads at 0 or
    ~6.25 are fault codes for bad packets, not real measurements.

    We flag any sample whose absolute deviation from the overall median
    exceeds 0.5 (which is ~5000× the normal band width) as a fault,
    replace it with NaN, and forward/back-fill. Almost all faults are
    single-sample blips, so interpolation is safe.
    """
    w = np.asarray(w, dtype=float).copy()
    med = np.median(w[np.isfinite(w)])
    fault_mask = np.abs(w - med) > 0.5
    w[fault_mask] = np.nan
    s = pd.Series(w).ffill().bfill()
    return s.values, int(fault_mask.sum())


def infer_lamp_state(current: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Threshold between the two current modes.  Uses the midpoint of the two
    largest kmeans-1D clusters, fallback to a robust midpoint.
    """
    # Simple 1-D two-mode split around the middle of the range,
    # then iterate (Lloyd's algorithm, 2 clusters).
    lo, hi = current.min(), current.max()
    c1, c2 = lo + 0.25 * (hi - lo), lo + 0.75 * (hi - lo)
    for _ in range(50):
        thr = 0.5 * (c1 + c2)
        m1, m2 = current[current < thr], current[current >= thr]
        if len(m1) == 0 or len(m2) == 0:
            break
        n1, n2 = m1.mean(), m2.mean()
        if abs(n1 - c1) < 1e-9 and abs(n2 - c2) < 1e-9:
            c1, c2 = n1, n2
            break
        c1, c2 = n1, n2
    thr = 0.5 * (c1 + c2)
    return (current >= thr).astype(int), thr


# ---------------------------------------------------------------------------
# 3. JUMP CORRECTION
# ---------------------------------------------------------------------------
def correct_jumps(methane: np.ndarray, k: float = 8.0) -> tuple[np.ndarray, list[tuple[int, float]]]:
    """
    Detect and remove step-level shifts in the methane series.

    A jump is a first-difference outlier: |Δ| > k * (1.4826 * MAD(Δ)).
    The default k=8 targets shifts far outside normal sample-to-sample noise
    without touching the ~0.01 ppm ordinary fluctuations.

    Returns:
      corrected : methane series with subsequent-value offsets removed
      jumps     : list of (index_of_new_sample, shift_magnitude)
    """
    d = np.diff(methane)
    med = np.median(d)
    mad = np.median(np.abs(d - med))
    sigma = 1.4826 * mad if mad > 0 else np.std(d)
    thr = k * sigma
    jump_idx = np.where(np.abs(d - med) > thr)[0]
    corrected = methane.copy()
    jumps = []
    for i in jump_idx:
        shift = d[i]
        corrected[i + 1:] -= shift
        jumps.append((int(i + 1), float(shift)))
    return corrected, jumps


# ---------------------------------------------------------------------------
# 4. CYCLE SEGMENTATION
# ---------------------------------------------------------------------------
@dataclass
class Cycle:
    idx: int          # cycle number (0..N-1)
    state: int        # 0 = OFF, 1 = ON
    start: int
    end: int          # exclusive
    t_start: pd.Timestamp
    t_end: pd.Timestamp
    mean_methane: float
    mean_windspeed: float
    n: int


def segment_cycles(df: pd.DataFrame) -> list[Cycle]:
    state = df["lamp"].values
    change = np.flatnonzero(np.diff(state) != 0) + 1
    edges = np.r_[0, change, len(state)]
    cycles = []
    for k in range(len(edges) - 1):
        a, b = edges[k], edges[k + 1]
        cycles.append(Cycle(
            idx=k, state=int(state[a]),
            start=int(a), end=int(b),
            t_start=df["time"].iloc[a], t_end=df["time"].iloc[b - 1],
            mean_methane=float(df["methane_corr"].iloc[a:b].mean()),
            mean_windspeed=float(df["windspeed"].iloc[a:b].mean()),
            n=int(b - a),
        ))
    return cycles


# ---------------------------------------------------------------------------
# 5. STATISTICS
# ---------------------------------------------------------------------------
def per_cycle_effects(cycles: list[Cycle]) -> pd.DataFrame:
    """
    For every ON cycle sandwiched between two OFF cycles, compute
        effect = mean_ON - 0.5 * (mean_OFF_prev + mean_OFF_next)
    This first-difference is robust against residual drift.
    """
    rows = []
    for i in range(1, len(cycles) - 1):
        c = cycles[i]
        if c.state != 1: continue
        prev_c, next_c = cycles[i - 1], cycles[i + 1]
        if prev_c.state != 0 or next_c.state != 0: continue
        baseline = 0.5 * (prev_c.mean_methane + next_c.mean_methane)
        rows.append({
            "cycle": c.idx,
            "t_mid": c.t_start + (c.t_end - c.t_start) / 2,
            "effect": c.mean_methane - baseline,
            "mean_windspeed": c.mean_windspeed,
        })
    return pd.DataFrame(rows)


def group_tests(df: pd.DataFrame) -> dict:
    on  = df.loc[df["lamp"] == 1, "methane_corr"].values
    off = df.loc[df["lamp"] == 0, "methane_corr"].values
    t_stat, t_p = stats.ttest_ind(on, off, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(on, off, alternative="two-sided")
    return {
        "n_on": len(on), "n_off": len(off),
        "mean_on": on.mean(),  "mean_off": off.mean(),
        "median_on": np.median(on), "median_off": np.median(off),
        "std_on": on.std(ddof=1), "std_off": off.std(ddof=1),
        "diff": on.mean() - off.mean(),
        "welch_t": t_stat, "welch_p": t_p,
        "mannwhitney_U": u_stat, "mannwhitney_p": u_p,
    }


def paired_cycle_test(effects: pd.DataFrame) -> dict:
    e = effects["effect"].values
    t_stat, t_p = stats.ttest_1samp(e, 0.0)
    try:
        w_stat, w_p = stats.wilcoxon(e, alternative="two-sided")
    except ValueError:
        w_stat, w_p = np.nan, np.nan
    ci = stats.t.interval(0.95, len(e) - 1, loc=e.mean(),
                          scale=stats.sem(e)) if len(e) > 1 else (np.nan, np.nan)
    return {
        "n_cycles": len(e),
        "mean_effect": e.mean(), "median_effect": np.median(e),
        "sd_effect": e.std(ddof=1) if len(e) > 1 else np.nan,
        "ci95_low": ci[0], "ci95_high": ci[1],
        "t_stat": t_stat, "t_p": t_p,
        "wilcoxon_W": w_stat, "wilcoxon_p": w_p,
    }


def windspeed_analysis(df: pd.DataFrame, effects: pd.DataFrame) -> dict:
    out = {}
    r_all, p_all = stats.pearsonr(df["windspeed"], df["methane_corr"])
    rs_all, ps_all = stats.spearmanr(df["windspeed"], df["methane_corr"])
    out["sample_pearson_r"]  = r_all; out["sample_pearson_p"]  = p_all
    out["sample_spearman_r"] = rs_all; out["sample_spearman_p"] = ps_all
    if len(effects) >= 3:
        r_e, p_e = stats.pearsonr(effects["mean_windspeed"], effects["effect"])
        rs_e, ps_e = stats.spearmanr(effects["mean_windspeed"], effects["effect"])
        slope, intercept, _, p_val, stderr = stats.linregress(
            effects["mean_windspeed"], effects["effect"])
        out.update({
            "effect_pearson_r": r_e, "effect_pearson_p": p_e,
            "effect_spearman_r": rs_e, "effect_spearman_p": ps_e,
            "effect_slope": slope, "effect_intercept": intercept,
            "effect_slope_p": p_val, "effect_slope_stderr": stderr,
        })
    return out


def multi_regression(df: pd.DataFrame) -> dict:
    """OLS: methane_corr ~ lamp + windspeed + lamp:windspeed via normal equations."""
    y = df["methane_corr"].values
    x1 = df["lamp"].values.astype(float)
    x2 = df["windspeed"].values
    X = np.column_stack([np.ones_like(y), x1, x2, x1 * x2])
    names = ["intercept", "lamp(ON=1)", "windspeed", "lamp:windspeed"]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ beta
    resid = y - yhat
    n, p = X.shape
    dof = n - p
    sigma2 = (resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    tvals = beta / se
    pvals = 2 * (1 - stats.t.cdf(np.abs(tvals), dof))
    ss_tot = ((y - y.mean()) ** 2).sum()
    ss_res = (resid ** 2).sum()
    r2 = 1 - ss_res / ss_tot
    return {
        "r2": r2, "n": n, "dof": dof,
        "coef": dict(zip(names, beta)),
        "se":   dict(zip(names, se)),
        "t":    dict(zip(names, tvals)),
        "p":    dict(zip(names, pvals)),
    }


# ---------------------------------------------------------------------------
# 6. PLOT
# ---------------------------------------------------------------------------
def make_plot(df: pd.DataFrame, cycles: list[Cycle], out_png: str):
    fig, ax = plt.subplots(figsize=(12, 4.2))

    # ON/OFF background shading
    for c in cycles:
        color = "#FFF3A0" if c.state == 1 else "#B8DDF5"
        ax.axvspan(df["time"].iloc[c.start],
                   df["time"].iloc[c.end - 1] if c.end < len(df) else df["time"].iloc[-1],
                   facecolor=color, alpha=0.85, zorder=0)

    # methane
    ax.plot(df["time"], df["methane_corr"], color="black", lw=0.7, zorder=3)
    ax.axhline(df["methane_corr"].mean(), color="red", ls="--", lw=1, zorder=4)

    ymin, ymax = np.nanmin(df["methane_corr"]), np.nanmax(df["methane_corr"])
    span = ymax - ymin
    w = df["windspeed"].values.astype(float)
    w_r = (w - np.nanmin(w)) / (np.nanmax(w) - np.nanmin(w) + 1e-12)
    w_scaled = ymin + 0.15 * span + 0.20 * span * w_r
    ax.plot(df["time"], w_scaled, color="#4E8C6E", lw=0.7, zorder=2)
    legend_elems = [
        Patch(facecolor="#FFF3A0", edgecolor="k", label="ON"),
        Patch(facecolor="#B8DDF5", edgecolor="k", label="OFF"),
        plt.Line2D([0], [0], color="red", ls="--", label="overall mean"),
        plt.Line2D([0], [0], color="#4E8C6E", label="windspeed (rescaled)"),
    ]

    ax.set_title("Methane — ON (yellow) vs OFF (blue) cycles")
    ax.set_ylabel("Methane (ppm)"); ax.set_xlabel("Time")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    ax.legend(handles=legend_elems, loc="upper left", framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 7. PDF
# ---------------------------------------------------------------------------
def fmt_p(p: float) -> str:
    if np.isnan(p): return "n/a"
    if p < 1e-4:   return "< 1e-4"
    return f"{p:.4f}"


def build_pdf(out_pdf, plot_png, df, cycles, jumps, group, cycle_test,
              wind, reg, thr, n_trimmed, n_wind_faults):
    doc = SimpleDocTemplate(out_pdf, pagesize=letter,
                            leftMargin=0.6*inch, rightMargin=0.6*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    body = styles["BodyText"]; h1 = styles["Heading1"]; h2 = styles["Heading2"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)

    els = []
    els.append(Paragraph("Lamp-Controller Sensor Log — Statistical Report", h1))
    els.append(Paragraph(
        f"Source: <b>{df.attrs.get('source','')}</b> · "
        f"Samples used: {len(df)} · Span: {df['time'].iloc[0]} → {df['time'].iloc[-1]}",
        small))
    els.append(Spacer(1, 8))

    # --- data quality ---
    els.append(Paragraph("1. Data preparation", h2))
    n_on_c  = sum(1 for c in cycles if c.state == 1)
    n_off_c = sum(1 for c in cycles if c.state == 0)
    if n_trimmed > 0:
        els.append(Paragraph(
            f"<b>Pre-experiment trim:</b> {n_trimmed} samples before the first "
            f"OFF→ON transition were dropped (lamp had not yet started cycling).",
            body))
    if n_wind_faults > 0:
        els.append(Paragraph(
            f"<b>Windspeed cleanup:</b> {n_wind_faults} sample(s) with fault-code "
            f"reads (values far outside the operating band) were replaced by "
            f"interpolation from neighbouring valid samples.", body))
    els.append(Paragraph(
        f"Lamp state was inferred from driver current using a bimodal split at "
        f"threshold <b>{thr:.3f} A</b> (below = OFF, above = ON). "
        f"Cycles identified: {n_on_c} ON, {n_off_c} OFF.", body))
    els.append(Paragraph(
        f"Baseline step-jumps were detected as first-difference outliers "
        f"(|Δ| &gt; 8·MAD-scaled σ) and removed by subtracting each shift from "
        f"subsequent samples. Jumps corrected: <b>{len(jumps)}</b>.", body))
    if jumps:
        rows = [["#", "sample idx", "time", "shift (ppm)"]]
        for k, (i, s) in enumerate(jumps, 1):
            rows.append([str(k), str(i),
                         df["time"].iloc[i].strftime("%H:%M:%S"),
                         f"{s:+.4f}"])
        t = Table(rows, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTSIZE", (0,0), (-1,-1), 8),
        ]))
        els.append(t); els.append(Spacer(1, 8))

    # --- plot ---
    els.append(Paragraph("2. Time series (drift-corrected)", h2))
    els.append(Image(plot_png, width=7.2*inch, height=2.6*inch))
    els.append(Spacer(1, 6))

    # --- group comparison ---
    els.append(Paragraph("3. Sample-level ON vs OFF comparison", h2))
    els.append(Paragraph(
        "Compares all samples pooled by lamp state, on the drift-corrected "
        "methane trace. Robust to short-term noise but not to slow trend.",
        body))
    g = group
    tbl = [["Metric", "ON", "OFF"],
           ["n",           f"{g['n_on']}",         f"{g['n_off']}"],
           ["mean (ppm)",  f"{g['mean_on']:.4f}",  f"{g['mean_off']:.4f}"],
           ["median",      f"{g['median_on']:.4f}",f"{g['median_off']:.4f}"],
           ["sd",          f"{g['std_on']:.4f}",   f"{g['std_off']:.4f}"]]
    els.append(Table(tbl, hAlign="LEFT", style=TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("FONTSIZE",(0,0),(-1,-1),9)])))
    els.append(Spacer(1, 6))
    els.append(Paragraph(
        f"ΔON−OFF = <b>{g['diff']:+.4f} ppm</b> · "
        f"Welch t = {g['welch_t']:.3f}, p = {fmt_p(g['welch_p'])} · "
        f"Mann-Whitney U = {g['mannwhitney_U']:.0f}, p = {fmt_p(g['mannwhitney_p'])}",
        body))

    # --- paired cycle test ---
    els.append(Spacer(1, 8))
    els.append(Paragraph("4. Cycle-paired ON effect (drift-robust)", h2))
    els.append(Paragraph(
        "Each complete ON cycle is compared to the mean of its neighbouring "
        "OFF cycles: effect = mean(ON) − ½·(mean(prev OFF)+mean(next OFF)). "
        "This first-differencing removes any residual baseline drift.", body))
    ct = cycle_test
    tbl = [["Metric", "Value"],
           ["ON cycles compared",           f"{ct['n_cycles']}"],
           ["mean effect (ppm)",            f"{ct['mean_effect']:+.4f}"],
           ["median effect (ppm)",          f"{ct['median_effect']:+.4f}"],
           ["sd",                           f"{ct['sd_effect']:.4f}"],
           ["95 % CI",                      f"[{ct['ci95_low']:+.4f}, {ct['ci95_high']:+.4f}]"],
           ["one-sample t (H0: effect=0)",  f"t = {ct['t_stat']:.3f}, p = {fmt_p(ct['t_p'])}"],
           ["Wilcoxon signed-rank",         f"W = {ct['wilcoxon_W']:.1f}, p = {fmt_p(ct['wilcoxon_p'])}"]]
    els.append(Table(tbl, hAlign="LEFT", style=TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("FONTSIZE",(0,0),(-1,-1),9)])))

    # --- windspeed ---
    els.append(PageBreak())
    els.append(Paragraph("5. Windspeed relationships", h2))
    w = wind
    tbl = [["Test", "r / ρ", "p"],
           ["methane ~ windspeed (Pearson)",  f"{w['sample_pearson_r']:+.3f}",  fmt_p(w['sample_pearson_p'])],
           ["methane ~ windspeed (Spearman)", f"{w['sample_spearman_r']:+.3f}", fmt_p(w['sample_spearman_p'])]]
    if "effect_pearson_r" in w:
        tbl += [
            ["ON-effect ~ windspeed (Pearson)",  f"{w['effect_pearson_r']:+.3f}",  fmt_p(w['effect_pearson_p'])],
            ["ON-effect ~ windspeed (Spearman)", f"{w['effect_spearman_r']:+.3f}", fmt_p(w['effect_spearman_p'])]]
    els.append(Table(tbl, hAlign="LEFT", style=TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("FONTSIZE",(0,0),(-1,-1),9)])))
    if "effect_slope" in w:
        els.append(Spacer(1, 6))
        els.append(Paragraph(
            f"OLS: effect = {w['effect_intercept']:+.4f} + "
            f"{w['effect_slope']:+.4f}·windspeed  "
            f"(slope SE = {w['effect_slope_stderr']:.4f}, p = {fmt_p(w['effect_slope_p'])}).",
            body))

    # --- multiple regression ---
    els.append(Spacer(1, 10))
    els.append(Paragraph("6. Multiple regression (sample-level)", h2))
    els.append(Paragraph(
        f"Model: methane_corr ~ lamp + windspeed + lamp·windspeed  ·  "
        f"R² = <b>{reg['r2']:.4f}</b> · n = {reg['n']}, dof = {reg['dof']}",
        body))
    tbl = [["Term", "coef", "SE", "t", "p"]]
    for name in reg["coef"]:
        tbl.append([name,
                    f"{reg['coef'][name]:+.5f}",
                    f"{reg['se'][name]:.5f}",
                    f"{reg['t'][name]:+.3f}",
                    fmt_p(reg['p'][name])])
    els.append(Table(tbl, hAlign="LEFT", style=TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.25,colors.grey),
        ("FONTSIZE",(0,0),(-1,-1),9)])))
    els.append(Spacer(1, 6))
    els.append(Paragraph(
        "Interpretation guide: the lamp coefficient is the ON−OFF shift at "
        "zero windspeed; the interaction term shows how that shift changes "
        "per unit of windspeed. A significant interaction means the lamp "
        "effect depends on wind.", small))

    # --- summary ---
    els.append(Spacer(1, 10))
    els.append(Paragraph("7. Summary of findings", h2))
    lamp_effect = reg["coef"]["lamp(ON=1)"]
    lamp_p = reg["p"]["lamp(ON=1)"]
    inter = reg["coef"]["lamp:windspeed"]
    inter_p = reg["p"]["lamp:windspeed"]
    bullet = []
    bullet.append(
        f"Cycle-paired mean ON effect: {ct['mean_effect']:+.4f} ppm "
        f"(95% CI [{ct['ci95_low']:+.4f}, {ct['ci95_high']:+.4f}], "
        f"paired t p={fmt_p(ct['t_p'])}).")
    bullet.append(
        f"Sample-level ON−OFF gap: {g['diff']:+.4f} ppm (Welch p={fmt_p(g['welch_p'])}).")
    bullet.append(
        f"Windspeed vs methane: r={wind['sample_pearson_r']:+.3f} "
        f"(p={fmt_p(wind['sample_pearson_p'])}).")
    if "effect_pearson_r" in wind:
        bullet.append(
            f"Per-cycle ON effect vs windspeed: r={wind['effect_pearson_r']:+.3f} "
            f"(p={fmt_p(wind['effect_pearson_p'])}).")
    bullet.append(
        f"Regression: lamp coef={lamp_effect:+.4f} (p={fmt_p(lamp_p)}), "
        f"lamp×wind interaction={inter:+.4f} (p={fmt_p(inter_p)}).")
    for b in bullet:
        els.append(Paragraph("• " + b, body))

    doc.build(els)


# ---------------------------------------------------------------------------
# 8. MAIN
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile", nargs="+",
                    help="one or more log files (any order; sorted by timestamp)")
    ap.add_argument("-o", "--out", default="lamp_report.pdf")
    ap.add_argument("--jump-k", type=float, default=8.0,
                    help="Jump-detection threshold in MAD-scaled sigmas (default 8)")
    args = ap.parse_args()

    df = parse_log(args.logfile)
    df.attrs["source"] = ", ".join(args.logfile)
    if len(df) < 100:
        sys.exit(f"Too few valid samples parsed ({len(df)}).")

    df["lamp"], thr = infer_lamp_state(df["current"].values)
    df, n_trimmed = trim_to_experiment(df)
    if len(df) < 100:
        sys.exit(f"Too few samples after trim ({len(df)}).")
    df["methane_corr"], jumps = correct_jumps(df["methane"].values, k=args.jump_k)
    df["windspeed"], n_wind_faults = clean_windspeed(df["windspeed"].values)

    cycles  = segment_cycles(df)
    effects = per_cycle_effects(cycles)
    group   = group_tests(df)
    cyc_t   = paired_cycle_test(effects) if len(effects) else {
        "n_cycles":0, "mean_effect":np.nan, "median_effect":np.nan,
        "sd_effect":np.nan, "ci95_low":np.nan, "ci95_high":np.nan,
        "t_stat":np.nan, "t_p":np.nan, "wilcoxon_W":np.nan, "wilcoxon_p":np.nan}
    wind    = windspeed_analysis(df, effects)
    reg     = multi_regression(df)

    png = "/tmp/_lamp_plot.png"
    make_plot(df, cycles, png)
    build_pdf(args.out, png, df, cycles, jumps, group, cyc_t, wind, reg, thr,
              n_trimmed, n_wind_faults)
    print(f"Wrote {args.out}  ({len(df)} samples, {n_trimmed} trimmed, "
          f"{len(cycles)} cycles, {len(jumps)} jumps corrected, "
          f"{n_wind_faults} wind faults interpolated)")


if __name__ == "__main__":
    main()
