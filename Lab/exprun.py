#!/usr/bin/env python3
"""
exprun.py - Run a multi-pin GPIO experiment with independent on/off cycles.

Usage:
    python3 exprun.py [pin,on_ms,off_ms,initial_state] ...

Example:
    python3 exprun.py [5,1000,4000,off] [6,500,2000,on]

Each pin cycles independently: starts in initial_state, holds for the
corresponding duration (on_ms or off_ms), then flips, and repeats.
Logs every state change with real timestamps to explog/.
"""

import sys
import re
import os
import time
import threading
from datetime import datetime

try:
    import RPi.GPIO as GPIO
    MOCK = False
except ImportError:
    MOCK = True
    print("[mock] RPi.GPIO not available — running in simulation mode")


def _gpio_setup():
    if not MOCK:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)


def _gpio_cleanup():
    if not MOCK:
        GPIO.cleanup()


def _pin_setup(pin, state):
    if not MOCK:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH if state else GPIO.LOW)
    else:
        print(f"[mock] setup pin {pin} initial={'HIGH' if state else 'LOW'}")


def _pin_set(pin, state):
    if not MOCK:
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
    else:
        print(f"[mock] pin {pin} -> {'HIGH' if state else 'LOW'}")


def parse_specs(args):
    specs = []
    pattern = re.compile(r'^\[(\d+),(\d+),(\d+),(on|off)\]$', re.IGNORECASE)
    for arg in args:
        m = pattern.match(arg.strip())
        if not m:
            print(f"Error: cannot parse argument '{arg}'")
            print("Expected format: [pin,on_ms,off_ms,on|off]")
            sys.exit(1)
        specs.append({
            'pin': int(m.group(1)),
            'on_ms': int(m.group(2)),
            'off_ms': int(m.group(3)),
            'initial': m.group(4).lower() == 'on',
        })
    return specs


def run_pin(spec, log_lock, log_file, stop_event):
    pin = spec['pin']
    on_ms = spec['on_ms']
    off_ms = spec['off_ms']
    state = spec['initial']

    def log(s):
        ts = datetime.now().isoformat(timespec='milliseconds')
        line = f"{ts}  pin={pin}  state={'on' if s else 'off'}\n"
        with log_lock:
            log_file.write(line)
            log_file.flush()
        print(line, end='')

    _pin_setup(pin, state)
    log(state)

    while not stop_event.is_set():
        hold_sec = (on_ms if state else off_ms) / 1000.0
        if stop_event.wait(timeout=hold_sec):
            break
        state = not state
        _pin_set(pin, state)
        log(state)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    specs = parse_specs(sys.argv[1:])

    os.makedirs('explog', exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join('explog', f'exp_{ts}.log')

    _gpio_setup()
    log_lock = threading.Lock()
    stop_event = threading.Event()

    with open(log_path, 'w') as log_file:
        pin_summary = ', '.join(
            f"{s['pin']} on={s['on_ms']}ms off={s['off_ms']}ms init={'on' if s['initial'] else 'off'}"
            for s in specs
        )
        header = (
            f"# experiment_start: {datetime.now().isoformat()}\n"
            f"# pins: {pin_summary}\n"
        )
        log_file.write(header)
        log_file.flush()

        threads = [
            threading.Thread(
                target=run_pin,
                args=(s, log_lock, log_file, stop_event),
                daemon=True,
            )
            for s in specs
        ]

        print(f"Experiment started — log: {log_path}")
        print("Press Ctrl+C to stop\n")

        for t in threads:
            t.start()

        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nStopping — forcing all pins low…")
            stop_event.set()

        for t in threads:
            t.join(timeout=2)

        for s in specs:
            _pin_set(s['pin'], False)
            ts = datetime.now().isoformat(timespec='milliseconds')
            with log_lock:
                log_file.write(f"{ts}  pin={s['pin']}  state=off  [forced]\n")

        log_file.write(f"# experiment_end: {datetime.now().isoformat()}\n")

    _gpio_cleanup()
    print(f"Log saved: {log_path}")


if __name__ == '__main__':
    main()
