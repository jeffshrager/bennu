#!/usr/bin/env python3
import sys
import argparse
from datetime import datetime, timedelta


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tsv_file')
    parser.add_argument('log_file')
    parser.add_argument('--timedelta', type=float, default=0,
                        help='seconds to subtract from log timestamps to align with TSV clock')
    args = parser.parse_args()

    events = parse_log(args.log_file, args.timedelta)

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
