#!/usr/bin/env python3
"""
annotate_tsv.py — Annotate a neurofeedback TSV file with GPIO/o3 event markers.

Takes a Presentation-style TSV (6+ tab-separated columns, HH:MM:SS time in col 0)
and automatically loads all log files from explog/ and o3logs/ (relative to this
script), merging events across all of them. For each second in the TSV that matches
a logged event, the script sets column 4 to 30000 (stimulus-present code) and
column 5 to the event text; rows with no matching event get column 4 = 0.

INPUT: TSV file
  - Header row: first field exactly TIME
  - Data rows:  field 0 = HH:MM:SS, fields 1–3 = data channels (untouched),
                field 4 = stimulus code (overwritten), field 5 = note (overwritten)

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

Usage:
  python3 annotate_tsv.py recording.tsv > annotated.tsv
  python3 annotate_tsv.py recording.tsv --timedelta 7200 > annotated.tsv
"""
import sys
import argparse
import glob
import os
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIRS = ['explog', 'o3logs']


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


def collect_all_events(delta_seconds):
    events = {}
    total = 0
    for log_dir in LOG_DIRS:
        pattern = os.path.join(SCRIPT_DIR, log_dir, '*.log')
        for path in sorted(glob.glob(pattern)):
            file_events = parse_log(path, delta_seconds)
            for key, notes in file_events.items():
                events.setdefault(key, []).extend(notes)
            print(f'# loaded {len(file_events)} events from {os.path.relpath(path, SCRIPT_DIR)}',
                  file=sys.stderr)
            total += len(file_events)
    print(f'# total events across all logs: {total}', file=sys.stderr)
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tsv_file')
    parser.add_argument('--timedelta', type=float, default=0,
                        help='seconds to subtract from log timestamps to align with TSV clock')
    args = parser.parse_args()

    events = collect_all_events(args.timedelta)

    with open(args.tsv_file) as f:
        for line in f:
            line = line.rstrip('\n')
            parts = line.split('\t')
            if parts[0] == 'TIME':
                print(line)
                continue
            key = parts[0]
            if key in events:
                parts[4] = '30000'
                parts[5] = '; '.join(events[key])
            else:
                parts[4] = '0'
            print('\t'.join(parts))


if __name__ == '__main__':
    main()
