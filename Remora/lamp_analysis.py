#!/usr/bin/env python3
"""
lamp_analysis.py
================
Statistical analysis of a lamp-controller sensor log (methane, windspeed,
current) and generation of a PDF report.

Input log lines (one per 5-s sample) look like:
    2026-05-02T17:18:54-0700 [INFO] Sensors: time=... methane=1.849 windspeed=4.09 current=0.325
    2026-05-02T17:19:24-0700 [ERROR] Error reading methane sensor: ...

Lamp state is inferred one of two ways, depending on what the log contains:
  - Quad-log rigs (GPIO-driven "bowport/bowstar/sternport/sternstar" quads;
    current sensor absent/always 0): state is read from "Quad <name> set to
    ON/OFF" events. ON = all quads simultaneously energized (the steady
    hold after the sequential ramp-up); OFF = all quads off. Samples taken
    while only *some* quads are on (the ramp-up/ramp-down transition) are
    excluded from the ON/OFF comparison rather than assigned to either
    state.
  - Current-sensor rigs: state is inferred from the driver current
    (bimodal: ~0.325 A OFF, ~0.60 A ON).
Baseline step-jumps in the methane trace (sensor recalibration ticks,
unrelated to the lamp cycle) are detected and removed.

The logs are read from a .tar.gz archive (unpacked to a temp directory).
This program only reports; for an interactive plot of the same data see
lamp_plot.py.

Usage:
    python3 lamp_analysis.py <logs.tar.gz> [-o report.pdf]
"""
from __future__ import annotations
import argparse, re, sys, io, os, tarfile, tempfile
from datetime import datetime
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import stats
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)


# ---------------------------------------------------------------------------
# 1. PARSING
# ---------------------------------------------------------------------------
LINE_RE = re.compile(
    r"time=(?P<t>\S+)\s+methane=(?P<m>[\w.\-]+)\s+"
    r"windspeed=(?P<w>[\w.\-]+)\s+current=(?P<c>[\w.\-]+)"
)


def extract_logs(tarball: str, dest: str) -> list[str]:
    """Unpack a .tar.gz into dest and return the paths of the regular files."""
    if not tarfile.is_tarfile(tarball):
        sys.exit(f"{tarball} is not a tar archive.")
    with tarfile.open(tarball, "r:*") as tf:
        # Only extract plain files, and never anything that would land
        # outside dest (absolute paths or ../ components).
        root = os.path.realpath(dest)
        members = [m for m in tf.getmembers() if m.isfile()
                   and os.path.realpath(os.path.join(dest, m.name)).startswith(root + os.sep)]
        tf.extractall(dest, members=members, filter="data")
    paths = [os.path.join(dest, m.name) for m in members]
    if not paths:
        sys.exit(f"No files found in {tarball}.")
    return sorted(paths)


def parse_log(paths: list[str]) -> pd.DataFrame:
    """Parse one or more log files, concatenate, sort by time, dedupe."""
    rows = []
    for path in paths:
        with open(path, errors="replace") as fh:
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


QUAD_RE = re.compile(r"^(?P<t>\S+).*Quad (?P<name>\w+) set to (?P<state>ON|OFF)")


def parse_quad_events(paths: list[str]) -> list[tuple[datetime, str, bool]]:
    """Parse 'Quad <name> set to ON/OFF' events from one or more log files."""
    events = []
    for path in paths:
        with open(path, errors="replace") as fh:
            for line in fh:
                m = QUAD_RE.search(line)
                if not m:
                    continue
                try:
                    t = datetime.fromisoformat(m["t"])
                except ValueError:
                    continue
                # Sensor timestamps (used for df["time"]) are naive local
                # time; strip the offset here so the two are comparable.
                t = t.replace(tzinfo=None)
                events.append((t, m["name"], m["state"] == "ON"))
    events.sort(key=lambda e: e[0])
    return events


def lamp_state_from_quads(
    times: pd.Series, events: list[tuple[datetime, str, bool]]
) -> tuple[np.ndarray, int]:
    """
    Derive lamp state per sensor sample from quad ON/OFF events.

    ON (1)  = every quad seen in the log is simultaneously energized (the
              steady hold after the sequential ramp-up).
    OFF (0) = every quad is off.
    Ramp (-1) = some but not all quads on (sequential ramp-up/down);
              excluded from the ON/OFF comparison.

    Returns the state array and the count of ramp samples.
    """
    quad_names = sorted({name for _, name, _ in events})
    n_quads = len(quad_names)
    on = {name: False for name in quad_names}
    lamp = np.zeros(len(times), dtype=int)
    ei = 0
    n_on = 0
    for i, t in enumerate(times):
        while ei < len(events) and events[ei][0] <= t:
            _, name, is_on = events[ei]
            if on[name] != is_on:
                on[name] = is_on
                n_on += 1 if is_on else -1
            ei += 1
        if n_on == n_quads:
            lamp[i] = 1
        elif n_on == 0:
            lamp[i] = 0
        else:
            lamp[i] = -1
    n_ramp = int(np.sum(lamp == -1))
    return lamp, n_ramp


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
    o_start: int = 0  # position in the full (unfiltered) sample sequence, inclusive
    o_end: int = 0    # inclusive


def segment_cycles(df: pd.DataFrame) -> list[Cycle]:
    state = df["lamp"].values
    orig = df["orig"].values if "orig" in df else np.arange(len(df))
    # A new cycle starts at a lamp-state change, or where samples were
    # removed (long-cycle exclusion) so a gap is never bridged.
    change = np.flatnonzero((np.diff(state) != 0) | (np.diff(orig) != 1)) + 1
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
            o_start=int(orig[a]), o_end=int(orig[b - 1]),
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
        if prev_c.o_end + 1 != c.o_start or c.o_end + 1 != next_c.o_start: continue
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
    if len(on) == 0 or len(off) == 0:
        # Lamp state never changed (e.g. a busted current sensor stuck at a
        # single reading, so everything is classified ON or everything
        # OFF) -- there is no ON/OFF contrast to test.
        return {
            "n_on": len(on), "n_off": len(off),
            "mean_on": float(on.mean()) if len(on) else np.nan,
            "mean_off": float(off.mean()) if len(off) else np.nan,
            "median_on": float(np.median(on)) if len(on) else np.nan,
            "median_off": float(np.median(off)) if len(off) else np.nan,
            "std_on": float(on.std(ddof=1)) if len(on) > 1 else np.nan,
            "std_off": float(off.std(ddof=1)) if len(off) > 1 else np.nan,
            "diff": np.nan,
            "welch_t": np.nan, "welch_p": np.nan,
            "mannwhitney_U": np.nan, "mannwhitney_p": np.nan,
        }
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


def _safe_corr(x, y, func) -> tuple[float, float]:
    """
    Run a scipy correlation function (pearsonr/spearmanr), returning NaNs
    instead of raising/warning when a busted sensor holds one side constant
    (e.g. all-zero or all-identical readings), which makes the correlation
    undefined.
    """
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    if len(x) < 2 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return np.nan, np.nan
    return func(x, y)


def windspeed_analysis(df: pd.DataFrame, effects: pd.DataFrame) -> dict:
    out = {}
    r_all, p_all = _safe_corr(df["windspeed"], df["methane_corr"], stats.pearsonr)
    rs_all, ps_all = _safe_corr(df["windspeed"], df["methane_corr"], stats.spearmanr)
    out["sample_pearson_r"]  = r_all; out["sample_pearson_p"]  = p_all
    out["sample_spearman_r"] = rs_all; out["sample_spearman_p"] = ps_all
    if len(effects) >= 3:
        r_e, p_e = _safe_corr(effects["mean_windspeed"], effects["effect"], stats.pearsonr)
        rs_e, ps_e = _safe_corr(effects["mean_windspeed"], effects["effect"], stats.spearmanr)
        if np.ptp(effects["mean_windspeed"].values) == 0:
            slope, intercept, p_val, stderr = np.nan, np.nan, np.nan, np.nan
        else:
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
    try:
        cov = sigma2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        # Design matrix is rank-deficient -- e.g. a busted sensor holds
        # lamp state or windspeed constant, making a column collinear with
        # the intercept. lstsq above still gives a (minimum-norm) fit, but
        # standard errors/t-tests on the coefficients are undefined.
        se = np.full(p, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        tvals = beta / se
        pvals = 2 * (1 - stats.t.cdf(np.abs(tvals), dof))
    ss_tot = ((y - y.mean()) ** 2).sum()
    ss_res = (resid ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return {
        "r2": r2, "n": n, "dof": dof,
        "coef": dict(zip(names, beta)),
        "se":   dict(zip(names, se)),
        "t":    dict(zip(names, tvals)),
        "p":    dict(zip(names, pvals)),
    }


# ---------------------------------------------------------------------------
# 6. PDF
# ---------------------------------------------------------------------------
def fmt_p(p: float) -> str:
    if np.isnan(p): return "n/a"
    if p < 1e-4:   return "< 1e-4"
    return f"{p:.4f}"


def stats_block(els, tag, group, cycle_test, wind, reg, body, h2, small):
    # --- group comparison ---
    els.append(Paragraph(f"{tag} — Sample-level ON vs OFF comparison", h2))
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
    els.append(Paragraph(f"{tag} — Cycle-paired ON effect (drift-robust)", h2))
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
    els.append(Paragraph(f"{tag} — Windspeed relationships", h2))
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
    els.append(Paragraph(f"{tag} — Multiple regression (sample-level)", h2))
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
    els.append(Paragraph(f"{tag} — Summary of findings", h2))
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


def build_pdf(out_pdf, df, cycles, jumps, variants, thr, n_trimmed,
              n_wind_faults, lamp_method="current", n_ramp=0, long_info=None):
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
    els.append(Paragraph("Data preparation", h2))
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
    if lamp_method == "quad-log":
        els.append(Paragraph(
            f"Lamp state was inferred from explicit 'Quad ... set to ON/OFF' log "
            f"events: ON = all quads simultaneously energized (the steady hold "
            f"after the sequential ramp-up), OFF = all quads off. "
            f"Cycles identified: {n_on_c} ON, {n_off_c} OFF.", body))
        if n_ramp > 0:
            els.append(Paragraph(
                f"<b>Ramp-up/ramp-down exclusion:</b> {n_ramp} sample(s) taken "
                f"while only some quads were energized (sequential lamp "
                f"start-up/shutdown) were excluded from the ON/OFF comparison.",
                body))
    else:
        els.append(Paragraph(
            f"Lamp state was inferred from driver current using a bimodal split at "
            f"threshold <b>{thr:.3f} A</b> (below = OFF, above = ON). "
            f"Cycles identified: {n_on_c} ON, {n_off_c} OFF.", body))
    els.append(Paragraph(
        f"Baseline step-jumps were detected as first-difference outliers "
        f"(|Δ| &gt; 8·MAD-scaled σ) and removed by subtracting each shift from "
        f"subsequent samples. Jumps corrected: <b>{len(jumps)}</b>.", body))
    if long_info and long_info["n_cycles"] > 0:
        els.append(Paragraph(
            f"<b>Long stretches:</b> {long_info['n_cycles']} ON/OFF stretch(es) "
            f"longer than {long_info['thr']:.0f} samples ({long_info['factor']:g}× the "
            f"median cycle length), {long_info['n_samples']} samples in total. "
            f"The lamp state during these is inferred from control signals "
            f"only and may be wrong (e.g. a reboot silently turns the lamps "
            f"off). All statistics below are therefore given twice: "
            f"<b>A</b> with all data, <b>B</b> with these stretches removed "
            f"(cycles are never paired across a removed stretch).", body))
    els.append(Paragraph(
        "Sample-level ON/OFF, cycle-paired, windspeed and regression results "
        "follow, one set per variant.", body))
    for k, (tag, v) in enumerate(variants):
        els.append(PageBreak())
        els.append(Paragraph(f"{tag}: {v['label']}", h1))
        els.append(Paragraph(
            f"Samples: {len(v['df'])} · cycles: {len(v['cycles'])}", small))
        stats_block(els, tag, v["group"], v["cycle_test"], v["wind"], v["reg"],
                    body, h2, small)

    doc.build(els)


# ---------------------------------------------------------------------------
# 8. MAIN
# ---------------------------------------------------------------------------
def drop_long_cycles(df: pd.DataFrame, cycles: list[Cycle], factor: float):
    """
    Remove samples belonging to unusually long ON/OFF stretches (longer than
    factor x the median cycle length). Returns (filtered df, number of long
    cycles, number of samples removed, length threshold in samples).
    """
    thr_n = factor * float(np.median([c.n for c in cycles]))
    long_c = [c for c in cycles if c.n > thr_n]
    if not long_c:
        return df, 0, 0, thr_n
    keep = np.ones(len(df), dtype=bool)
    for c in long_c:
        keep[c.start:c.end] = False
    return df.loc[keep].reset_index(drop=True), len(long_c), int((~keep).sum()), thr_n


def prepare(paths: list[str], jump_k: float = 8.0):
    """
    Parse logs and run the cleaning pipeline (lamp state, trim, jump and
    windspeed correction). Shared with lamp_plot.py so both see the same data.
    """
    df = parse_log(paths)
    if len(df) < 100:
        sys.exit(f"Too few valid samples parsed ({len(df)}).")

    quad_events = parse_quad_events(paths)
    if quad_events:
        lamp_method = "quad-log"
        thr = None
        df["lamp"], n_ramp = lamp_state_from_quads(df["time"], quad_events)
        df = df.loc[df["lamp"] != -1].reset_index(drop=True)
    else:
        lamp_method = "current"
        n_ramp = 0
        df["lamp"], thr = infer_lamp_state(df["current"].values)

    df, n_trimmed = trim_to_experiment(df)
    if len(df) < 100:
        sys.exit(f"Too few samples after trim ({len(df)}).")
    df["methane_corr"], jumps = correct_jumps(df["methane"].values, k=jump_k)
    df["windspeed"], n_wind_faults = clean_windspeed(df["windspeed"].values)
    df["orig"] = np.arange(len(df))
    return df, jumps, thr, n_trimmed, n_wind_faults, lamp_method, n_ramp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tarball", help="a .tar.gz containing the log files")
    ap.add_argument("-o", "--out", default="lamp_report.pdf")
    ap.add_argument("--jump-k", type=float, default=8.0,
                    help="Jump-detection threshold in MAD-scaled sigmas (default 8)")
    ap.add_argument("--long-factor", type=float, default=3.0,
                    help="ON/OFF stretches longer than this many times the "
                         "median cycle length are treated as 'long' and "
                         "excluded from variant B (default 3)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        paths = extract_logs(args.tarball, tmp)
        (df, jumps, thr, n_trimmed, n_wind_faults,
         lamp_method, n_ramp) = prepare(paths, args.jump_k)
    df.attrs["source"] = os.path.basename(args.tarball)

    def analyze(d):
        cyc = segment_cycles(d)
        eff = per_cycle_effects(cyc)
        return {
            "df": d, "cycles": cyc,
            "group": group_tests(d),
            "cycle_test": paired_cycle_test(eff) if len(eff) else {
                "n_cycles":0, "mean_effect":np.nan, "median_effect":np.nan,
                "sd_effect":np.nan, "ci95_low":np.nan, "ci95_high":np.nan,
                "t_stat":np.nan, "t_p":np.nan, "wilcoxon_W":np.nan, "wilcoxon_p":np.nan},
            "wind": windspeed_analysis(d, eff),
            "reg": multi_regression(d),
        }

    full = analyze(df)
    full["label"] = "all data"
    variants = [("A", full)]
    df_b, n_long, n_long_samples, thr_n = drop_long_cycles(
        df, full["cycles"], args.long_factor)
    long_info = {"n_cycles": n_long, "n_samples": n_long_samples,
                 "thr": thr_n, "factor": args.long_factor}
    if n_long:
        b = analyze(df_b)
        b["label"] = f"long stretches removed ({n_long} stretch(es), {n_long_samples} samples)"
        variants.append(("B", b))

    cycles = full["cycles"]
    build_pdf(args.out, df, cycles, jumps, variants, thr,
              n_trimmed, n_wind_faults, lamp_method, n_ramp, long_info)
    print(f"Wrote {args.out}  ({len(df)} samples, {n_trimmed} trimmed, "
          f"{n_ramp} ramp samples excluded, {len(cycles)} cycles, "
          f"{len(jumps)} jumps corrected, {n_wind_faults} wind faults interpolated, "
          f"{n_long} long stretches [{n_long_samples} samples] in variant B only)")


if __name__ == "__main__":
    main()
