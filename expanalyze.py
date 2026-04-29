# -*- coding: utf-8 -*-
"""
expanalyze.py -- Segment the data log by the experiment model and report stats + t-tests.

Usage:
    python3 expanalyze.py [data.tsv] [expmodel.txt]

Defaults to results/ax1.tsv and results/expmodel.txt.
Output is written to results/expmodel_stats.txt and also printed.

expmodel.txt format:
    Model
    <label>  <start_HHMMSS>  <end_HHMMSS>  <col1>  <col2>  ...
    ...
    Tests
    <labels_A>  <labels_B>        (tab-separated; each side is comma-joined labels)
    ...
"""

import sys
import math
import os
import argparse
from datetime import datetime

# ---------------------------------------------------------------------------
# Welch's t-test (no scipy needed)
# Uses the incomplete beta function via continued fractions (Numerical Recipes)
# ---------------------------------------------------------------------------
def _betacf(a, b, x):
    MAXIT, EPS, FPMIN = 200, 3e-7, 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, max(1.0 - qab * x / qap, FPMIN)
    d, h = 1.0 / d, 1.0 / d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 / max(1.0 + aa * d, FPMIN)
        c = max(1.0 + aa / c, FPMIN)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 / max(1.0 + aa * d, FPMIN)
        c = max(1.0 + aa / c, FPMIN)
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h

def _betai(a, b, x):
    if x <= 0.0: return 0.0
    if x >= 1.0: return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x)) * _betacf(a, b, x) / a
    else:
        return 1.0 - math.exp(lbeta + b * math.log(1.0 - x) + a * math.log(x)) * _betacf(b, a, 1.0 - x) / b

def welch_ttest(a, b):
    """Two-tailed Welch's t-test. Returns (t, p)."""
    na, nb = len(a), len(b)
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((v - ma) ** 2 for v in a) / (na - 1)
    vb = sum((v - mb) ** 2 for v in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    t  = (ma - mb) / se
    df_num = (va / na + vb / nb) ** 2
    df_den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = df_num / df_den
    p  = _betai(df / 2.0, 0.5, df / (df + t * t))
    return t, p

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--resultsdir', default='results',
                    help='Directory containing ax1.tsv and expmodel.txt (default: results)')
parser.add_argument('tsv',   nargs='?', help='Override data file path')
parser.add_argument('model', nargs='?', help='Override model file path')
args = parser.parse_args()

RESULTS_DIR = args.resultsdir
TSV_PATH    = args.tsv   or os.path.join(RESULTS_DIR, 'ax1.tsv')
MODEL_PATH  = args.model or os.path.join(RESULTS_DIR, 'expmodel.txt')
OUT_PATH    = os.path.join(RESULTS_DIR, 'expmodel_stats.txt')

# ---------------------------------------------------------------------------
# Load TSV
# ---------------------------------------------------------------------------
timestamps = []
values     = []

with open(TSV_PATH) as f:
    next(f)   # skip header
    for line in f:
        line = line.strip()
        if not line:
            continue
        ts_str, val_str = line.split('\t')
        timestamps.append(datetime.fromisoformat(ts_str))
        values.append(float(val_str))

data_date = timestamps[0].date()
print(f'Loaded {len(values)} samples  ({timestamps[0]}  ->  {timestamps[-1]})')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def hhmmss_to_datetime(s):
    s = s.strip()
    h, m, sec = int(s[0:2]), int(s[2:4]), int(s[4:6])
    return datetime.combine(data_date, datetime.min.time().replace(hour=h, minute=m, second=sec))

def nearest_index(target_dt):
    best_i, best_gap = 0, abs((timestamps[0] - target_dt).total_seconds())
    for i, ts in enumerate(timestamps):
        gap = abs((ts - target_dt).total_seconds())
        if gap < best_gap:
            best_i, best_gap = i, gap
    return best_i

def seg_stats(vals):
    n    = len(vals)
    mn   = min(vals)
    mx   = max(vals)
    mean = sum(vals) / n
    sd   = math.sqrt(sum((v - mean) ** 2 for v in vals) / n) if n > 1 else 0.0
    return n, mn, mx, mean, sd

# ---------------------------------------------------------------------------
# Parse expmodel.txt
# ---------------------------------------------------------------------------
segments = {}   # label -> dict with vals and metadata
tests    = []   # list of (left_labels, right_labels)

with open(MODEL_PATH) as f:
    section = None
    for line in f:
        line = line.rstrip('\n')
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == 'Model':
            section = 'model'
            continue
        if stripped == 'Tests':
            section = 'tests'
            continue

        if section == 'model':
            parts = stripped.split('\t')
            label      = parts[0].strip()
            start_str  = parts[1].strip()
            end_str    = parts[2].strip()
            conditions = [p.strip() for p in parts[3:]]

            start_dt = hhmmss_to_datetime(start_str)
            end_dt   = hhmmss_to_datetime(end_str)
            i0 = nearest_index(start_dt)
            i1 = nearest_index(end_dt)
            if i0 > i1:
                i0, i1 = i1, i0
            seg_vals = values[i0 : i1 + 1]

            segments[label] = {
                'start_str':  start_str,
                'end_str':    end_str,
                'conditions': conditions,
                'i0':         i0,
                'i1':         i1,
                'vals':       seg_vals,
            }

        elif section == 'tests':
            cols = stripped.split('\t')
            if len(cols) >= 2:
                left  = [l.strip() for l in cols[0].split(',')]
                right = [r.strip() for r in cols[1].split(',')]
                tests.append((left, right))

# ---------------------------------------------------------------------------
# Build output
# ---------------------------------------------------------------------------
out_lines = []

def emit(s=''):
    out_lines.append(s)
    print(s)

# -- Segment stats table --
emit('=== Segment Stats ===')
emit()
col_w = max(len(c) for s in segments.values() for c in s['conditions']) + 1
hdr = (f"{'seg':>4}  {'start':>8}  {'end':>8}  "
       f"{'conditions':<{3 + col_w * 3}}  "
       f"{'n':>5}  {'min':>9}  {'max':>9}  {'mean':>9}  {'sd':>9}  "
       f"{'actual range'}")
emit(hdr)
emit('-' * len(hdr))

for label, s in segments.items():
    cond_str = '  '.join(f'{c:<{col_w}}' for c in s['conditions'])
    n, mn, mx, mean, sd = seg_stats(s['vals'])
    actual = (f"[{timestamps[s['i0']].strftime('%H:%M:%S')} - "
              f"{timestamps[s['i1']].strftime('%H:%M:%S')}]")
    emit(f"{label:>4}  {s['start_str']:>8}  {s['end_str']:>8}  "
         f"{cond_str}  "
         f"{n:>5}  {mn:>9.4f}  {mx:>9.4f}  {mean:>9.4f}  {sd:>9.4f}  {actual}")

# -- T-tests --
if tests:
    emit()
    emit('=== T-tests (Welch) ===')
    emit()
    for left_labels, right_labels in tests:
        left_vals  = [v for lbl in left_labels  for v in segments[lbl]['vals']]
        right_vals = [v for lbl in right_labels for v in segments[lbl]['vals']]

        t, p = welch_ttest(left_vals, right_vals)

        left_str  = '+'.join(left_labels)
        right_str = '+'.join(right_labels)
        ln, lmean, lsd = len(left_vals),  sum(left_vals)  / len(left_vals),  math.sqrt(sum((v - sum(left_vals)/len(left_vals))**2  for v in left_vals)  / len(left_vals))
        rn, rmean, rsd = len(right_vals), sum(right_vals) / len(right_vals), math.sqrt(sum((v - sum(right_vals)/len(right_vals))**2 for v in right_vals) / len(right_vals))

        emit(f"  {left_str}  vs  {right_str}")
        emit(f"    left : n={ln}  mean={lmean:.4f}  sd={lsd:.4f}")
        emit(f"    right: n={rn}  mean={rmean:.4f}  sd={rsd:.4f}")
        emit(f"    t={t:.4f}  p={p:.6f}{'  ***' if p < 0.001 else '  **' if p < 0.01 else '  *' if p < 0.05 else ''}")
        emit()

# ---------------------------------------------------------------------------
# Write output file
# ---------------------------------------------------------------------------
with open(OUT_PATH, 'w') as f:
    f.write('\n'.join(out_lines) + '\n')

print(f'\nWritten to {OUT_PATH}')
