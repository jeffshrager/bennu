#!/usr/bin/env python3
"""
annotate_tsv.py — Annotate a neurofeedback TSV file with GPIO/o3 event markers.

Takes a Presentation-style TSV (6+ tab-separated columns, HH:MM:SS time in col 0)
and automatically loads all log files from explog/ and o3logs/ (relative to this
script), merging events across all of them. For each second in the TSV that matches
a logged event, the script sets column 4 to 30000 (stimulus-present code) and
column 5 to the event text; rows with no matching event get column 4 = 0.

A trailing "raw_o3" column is appended with the value following "raw=" on the
matching o3logs/ line for that second. Non-numeric or non-decimal raw values
(e.g. "None", ".", "2") are replaced with the last known good decimal value;
if none has been seen yet, "NaN" is used. Readings that look like a decimal
point was dropped by the OCR (e.g. "2194" instead of "21.94") are recovered
by dividing by 10 or 100 when the result lands within --max-delta of the
last known good value — the same "Smart Decimal Recovery" heuristic used by
HeuristicFilter.add_reading in o3.py.

INPUT: TSV file
  - Header row: first field exactly TIME; must contain "ping" and "note"
    columns (case-insensitive) — if either is missing it is appended.
  - Data rows:  field 0 = HH:MM:SS, the ping column holds the stimulus code
    (overwritten) and the note column holds the event text (overwritten);
    rows shorter than the header are padded with empty fields as needed.

LOG SOURCES (auto-discovered, no argument needed):
  explog/   — exprun.py state-change logs (exp_YYYYMMDD_HHMMSS.log)
  o3logs/   — o3.py OCR/GPIO logs       (o3_YYYYMMDD_HHMMSS.log)
  Each log line: YYYY-MM-DDTHH:MM:SS[.mmm]  <event text...>
  Lines starting with # are skipped.

OUTPUT: annotated TSV on stdout

ARGS:
  tsv_file     path to the TSV to annotate
  --timedelta  seconds to subtract from all log timestamps before matching
               (use to align the log wall clocks with the TSV clock)
               NOTE THAT IF THE WALL CLOCK (LOG CLOCK) IS BEHIND THE TSV (LT)
               CLOCK, THEN THE TIME DELTA WILL BE NEGATIVE!
  --o3log      path to a specific o3 log file to use for raw_o3, instead of
               auto-discovering files in o3logs/

Usage:
  python3 annotate_tsv.py recording.tsv > annotated.tsv
  python3 annotate_tsv.py recording.tsv --timedelta 7200 > annotated.tsv
  python3 annotate_tsv.py recording.tsv --o3log o3logs/o3_20260604_113710.log > annotated.tsv
"""
import sys
import argparse
import glob
import os
from datetime import datetime, timedelta

LOG_DIRS = ['explog']
RAW_LOG_DIR = 'o3logs'


def resolve_raw_reading(raw_str, last_good, max_delta=1.5):
    """Validate raw_str, recovering OCR misreads that dropped the decimal
    point (e.g. "2194" instead of "21.94"), mirroring the "Smart Decimal
    Recovery" and "Hard Range Constraint" steps in HeuristicFilter.add_reading
    (o3.py).

    Returns a formatted value string if raw_str is a good (or recovered)
    decimal reading, else None.
    """
    has_dot = '.' in raw_str
    try:
        val = float(raw_str)
    except ValueError:
        return None

    # 1. Smart Decimal Recovery
    if val > 50.00 and last_good is not None:
        last_good_val = float(last_good)
        for divisor in (10.0, 100.0):
            candidate = val / divisor
            if abs(candidate - last_good_val) <= max_delta:
                return f'{candidate:.2f}'

    # 2. Hard Range Constraint
    if not (0.00 <= val <= 50.00):
        return None

    # A bare integer (no decimal point, not recovered above) is too
    # ambiguous to trust as a reading.
    if not has_dot:
        return None

    return raw_str


def parse_log(log_file, delta_seconds):
    events = {}  # HH:MM:SS -> list of note strings
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                dt = datetime.fromisoformat(parts[0])
            except ValueError:
                continue
            dt -= timedelta(seconds=delta_seconds)
            key = dt.strftime('%H:%M:%S')
            note = ' '.join(parts[1:])
            events.setdefault(key, []).append(note)
    return events


def parse_raw_log(log_file, delta_seconds):
    entries = []  # list of (HH:MM:SS, raw_str) in file order
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                dt = datetime.fromisoformat(parts[0])
            except ValueError:
                continue
            raw_str = None
            for token in parts[1:]:
                if token.startswith('raw='):
                    raw_str = token[len('raw='):]
                    break
            if raw_str is None:
                continue
            dt -= timedelta(seconds=delta_seconds)
            key = dt.strftime('%H:%M:%S')
            entries.append((key, raw_str))
    return entries


def collect_raw_values(delta_seconds, o3log=None, max_delta=1.5):
    raw_by_key = {}
    last_good = None
    if o3log:
        paths = [o3log]
    else:
        pattern = os.path.join(RAW_LOG_DIR, '*.log')
        paths = sorted(glob.glob(pattern))
    for path in paths:
        for key, raw_str in parse_raw_log(path, delta_seconds):
            resolved = resolve_raw_reading(raw_str, last_good, max_delta)
            if resolved is not None:
                last_good = resolved
                value = resolved
            else:
                value = last_good if last_good is not None else 'NaN'
            raw_by_key[key] = value
    return raw_by_key


def collect_all_events(delta_seconds):
    events = {}
    total = 0
    for log_dir in LOG_DIRS:
        pattern = os.path.join(log_dir, '*.log')
        for path in sorted(glob.glob(pattern)):
            file_events = parse_log(path, delta_seconds)
            for key, notes in file_events.items():
                events.setdefault(key, []).extend(notes)
            print(f'# loaded {len(file_events)} events from {path}', file=sys.stderr)
            total += len(file_events)
    print(f'# total events across all logs: {total}', file=sys.stderr)
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tsv_file')
    parser.add_argument('--timedelta', type=float, default=0,
                        help='seconds to subtract from log timestamps to align with TSV clock')
    parser.add_argument('--o3log',
                        help='path to a specific o3 log file to use for raw_o3, '
                             'instead of auto-discovering files in o3logs/')
    parser.add_argument('--max-delta', type=float, default=1.5,
                        help='max allowed change from the last good raw_o3 value '
                             'when recovering a dropped decimal point (default: 1.5)')
    args = parser.parse_args()

    events = collect_all_events(args.timedelta)
    raw_by_key = collect_raw_values(args.timedelta, args.o3log, args.max_delta)

    with open(args.tsv_file) as f:
        lines = [line.rstrip('\n') for line in f]

    header = lines[0].split('\t')
    lower_header = [h.lower() for h in header]
    if 'ping' in lower_header:
        ping_idx = lower_header.index('ping')
    else:
        header.append('ping')
        ping_idx = len(header) - 1
    if 'note' in lower_header:
        note_idx = lower_header.index('note')
    else:
        header.append('note')
        note_idx = len(header) - 1
    header.append('raw_o3')
    print('\t'.join(header))

    last_raw = None
    for line in lines[1:]:
        parts = line.split('\t')
        while len(parts) <= max(ping_idx, note_idx):
            parts.append('')
        key = parts[0]
        if key in events:
            parts[ping_idx] = '30000'
            parts[note_idx] = '; '.join(events[key])
        else:
            parts[ping_idx] = '0'
        if key in raw_by_key:
            last_raw = raw_by_key[key]
        parts.append(last_raw if last_raw is not None else 'NaN')
        print('\t'.join(parts))


if __name__ == '__main__':
    main()
