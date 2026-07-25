#!/usr/bin/env python3
"""
Extract lamp ON/OFF cycle data from lamp_controller.log* files.
Run from the directory containing the log files.
Writes cycles.tsv in the same directory.
"""

import re
import glob
import os
import sys
import argparse

SENSOR_RE = re.compile(r'Sensors: time=(\S+) methane=(\S+) windspeed=(\S+) current=(\S+)')
LAMP_RE = re.compile(r'Quad bowport set to (ON|OFF)')

parser = argparse.ArgumentParser()
parser.add_argument('--min-samples', type=int, default=50,
                    help='Drop phases with fewer than this many samples (default: 50)')
args = parser.parse_args()

def file_sort_key(path):
    basename = os.path.basename(path)
    suffix = basename[len('lamp_controller.log'):]
    if suffix == '':
        return 0
    return int(suffix.lstrip('.'))

files = sorted(glob.glob('lamp_controller.log*'), key=file_sort_key, reverse=True)
if not files:
    print("No lamp_controller.log* files found.", file=sys.stderr)
    sys.exit(1)

print(f"Processing files (oldest first): {files}", file=sys.stderr)

phases = []
current_condition = None
current_readings = []
misread_count = 0
pre_lamp_count = 0

for filepath in files:
    with open(filepath) as f:
        for line in f:
            lamp_match = LAMP_RE.search(line)
            if lamp_match:
                new_condition = lamp_match.group(1)
                if new_condition != current_condition:
                    if current_condition is not None:
                        phases.append((current_condition, current_readings))
                    current_condition = new_condition
                    current_readings = []

            sensor_match = SENSOR_RE.search(line)
            if sensor_match:
                time_val, methane, windspeed, current_val = sensor_match.groups()
                if methane == 'NA':
                    misread_count += 1
                    continue
                if current_condition is None:
                    pre_lamp_count += 1
                    continue
                current_readings.append((time_val, methane, windspeed, current_val))

# Flush last in-progress phase
if current_condition is not None and current_readings:
    phases.append((current_condition, current_readings))

# Drop last (incomplete) phase
if phases:
    last_cond, last_readings = phases.pop()
    print(f"Last incomplete phase dropped: condition={last_cond}, samples={len(last_readings)}", file=sys.stderr)

# Drop short phases (test pulses)
short_dropped = [(c, r) for c, r in phases if len(r) < args.min_samples]
phases = [(c, r) for c, r in phases if len(r) >= args.min_samples]
if short_dropped:
    print(f"Short phases dropped (< {args.min_samples} samples): {len(short_dropped)} "
          f"({', '.join(f'{c}:{len(r)}' for c, r in short_dropped)})", file=sys.stderr)

# Stats
on_phases  = [(c, r) for c, r in phases if c == 'ON']
off_phases = [(c, r) for c, r in phases if c == 'OFF']
n_on  = sum(len(r) for _, r in on_phases)
n_off = sum(len(r) for _, r in off_phases)
n_cycles = min(len(on_phases), len(off_phases))

print(f"Misreads (methane=NA) dropped:   {misread_count}", file=sys.stderr)
print(f"Pre-lamp readings skipped:        {pre_lamp_count}", file=sys.stderr)
print(f"Complete cycles (ON+OFF pairs):   {n_cycles}", file=sys.stderr)
print(f"ON  phases: {len(on_phases):3d}   total samples: {n_on}", file=sys.stderr)
print(f"OFF phases: {len(off_phases):3d}   total samples: {n_off}", file=sys.stderr)

# Write TSV
outfile = 'cycles.tsv'
with open(outfile, 'w') as out:
    out.write('condition\ttime\tmethane\twindspeed\tcurrent\n')
    for condition, readings in phases:
        for time_val, methane, windspeed, current_val in readings:
            out.write(f'{condition}\t{time_val}\t{methane}\t{windspeed}\t{current_val}\n')

print(f"Wrote {outfile}", file=sys.stderr)
