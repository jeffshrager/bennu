#!/usr/bin/env python3
"""
labrun.py - Manifest-driven runner for a lab bench experiment.

Usage:
    python3 labrun.py <experiment_name> [--dry-run]

Reads $EXPERIMENTS/<experiment_name>/manifest.json (operator-authored, see
example_manifest.json), spawns o3.py (ozone, GPIO pin 6) and exprun.py (lamp,
GPIO pin 5) as subprocesses for the manifest's duration, and writes every
output file back into $EXPERIMENTS/<experiment_name>/ — nothing this run
produces ever lands inside the git repo.

--dry-run validates the manifest and prints the resolved command lines and
output layout without spawning anything or touching any pin.
"""

import argparse
import difflib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = REPO_ROOT / "Lab"

PIN_ROLES = {5: "lamp", 6: "ozone"}

TOP_REQUIRED = {"experiment", "date", "operator", "duration_min", "conditions", "lamp", "ozone"}
TOP_OPTIONAL = {"notes"}
CONDITIONS_REQUIRED = {"methane_sensor", "methane_ppm", "flow_lpm", "flow_control"}
LAMP_REQUIRED = {"pin", "on_ms", "off_ms", "initial"}
OZONE_REQUIRED = {
    "setpoint", "tickle_low_threshold", "pin", "gpio_ms",
    "tickle_delay_ms", "max_delta", "forced_reset_count", "vidpos",
}


def fail(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_keys(d, required, optional, label, errors):
    allowed = required | optional
    for key in d:
        if key not in allowed:
            match = difflib.get_close_matches(key, allowed, n=1)
            hint = f" (did you mean '{match[0]}'?)" if match else ""
            errors.append(f"Unknown key '{label}.{key}'{hint}")
    for key in required:
        if key not in d:
            errors.append(f"Missing required key '{label}.{key}'")


def validate_manifest(manifest):
    errors = []
    if not isinstance(manifest, dict):
        fail("manifest.json must be a JSON object")

    check_keys(manifest, TOP_REQUIRED, TOP_OPTIONAL, "manifest", errors)

    conditions = manifest.get("conditions", {})
    if isinstance(conditions, dict):
        check_keys(conditions, CONDITIONS_REQUIRED, set(), "manifest.conditions", errors)
    else:
        errors.append("manifest.conditions must be an object")

    lamp = manifest.get("lamp", {})
    if isinstance(lamp, dict):
        check_keys(lamp, LAMP_REQUIRED, set(), "manifest.lamp", errors)
        if "pin" in lamp and lamp["pin"] != 5:
            errors.append(
                f"manifest.lamp.pin is {lamp['pin']!r}, but pin 5 is the lamp pin "
                f"(PIN_ROLES={PIN_ROLES}) — did you swap lamp/ozone pins?")
        if "initial" in lamp and lamp["initial"] not in ("on", "off"):
            errors.append("manifest.lamp.initial must be 'on' or 'off'")
        for k in ("on_ms", "off_ms"):
            if k in lamp and (not isinstance(lamp[k], int) or lamp[k] <= 0):
                errors.append(f"manifest.lamp.{k} must be a positive integer")
    else:
        errors.append("manifest.lamp must be an object")

    ozone = manifest.get("ozone", {})
    if isinstance(ozone, dict):
        check_keys(ozone, OZONE_REQUIRED, set(), "manifest.ozone", errors)
        if "pin" in ozone and ozone["pin"] != 6:
            errors.append(
                f"manifest.ozone.pin is {ozone['pin']!r}, but pin 6 is the ozone pin "
                f"(PIN_ROLES={PIN_ROLES}) — did you swap lamp/ozone pins?")
        if "vidpos" in ozone:
            vp = ozone["vidpos"]
            if not (isinstance(vp, list) and len(vp) == 4 and all(isinstance(v, int) for v in vp)):
                errors.append("manifest.ozone.vidpos must be a 4-element list of integers")
        if ("setpoint" in ozone and "tickle_low_threshold" in ozone
                and isinstance(ozone["setpoint"], (int, float))
                and isinstance(ozone["tickle_low_threshold"], (int, float))
                and ozone["setpoint"] < ozone["tickle_low_threshold"]):
            errors.append(
                "manifest.ozone.setpoint must not be below tickle_low_threshold "
                "(o3.py would refuse this at startup)")
    else:
        errors.append("manifest.ozone must be an object")

    if "duration_min" in manifest and (
            not isinstance(manifest["duration_min"], (int, float)) or manifest["duration_min"] <= 0):
        errors.append("manifest.duration_min must be a positive number")

    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def build_argv(manifest, exp_dir):
    ozone = manifest["ozone"]
    lamp = manifest["lamp"]

    ozone_argv = [
        sys.executable, str(LAB_DIR / "o3.py"),
        str(ozone["setpoint"]),
        "--target", str(ozone["setpoint"]),
        "-tlt", str(ozone["tickle_low_threshold"]),
        "--gpiopin", str(ozone["pin"]),
        "--gpio-ms", str(ozone["gpio_ms"]),
        "-tdms", str(ozone["tickle_delay_ms"]),
        "-md", str(ozone["max_delta"]),
        "-frc", str(ozone["forced_reset_count"]),
        "--vidpos", ",".join(str(v) for v in ozone["vidpos"]),
        "--log-dir", str(exp_dir / "o3logs"),
    ]
    lamp_spec = f"[{lamp['pin']},{lamp['on_ms']},{lamp['off_ms']},{lamp['initial']}]"
    lamp_argv = [sys.executable, str(LAB_DIR / "exprun.py"), lamp_spec]
    return ozone_argv, lamp_argv


def describe_layout(exp_dir):
    return (
        f"{exp_dir}/\n"
        "  manifest.json        (already present — operator authored)\n"
        "  run_record.json       (resolved manifest + argv + t0 + git rev + host)\n"
        "  runlog.tsv            (supervisor log)\n"
        "  explog/exp_*.log       (written by exprun.py)\n"
        "  o3logs/o3_*.log        (written by o3.py)\n"
        "  stdout_ozone.log\n"
        "  stdout_lamp.log\n"
        "  <LI-COR writes its own files here>\n"
    )


def get_git_rev():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def force_pins_low(log):
    for pin in (5, 6):
        try:
            subprocess.run(["pinctrl", "set", str(pin), "dl"], check=False)
            readback = subprocess.run(
                ["pinctrl", "get", str(pin)], capture_output=True, text=True, check=False)
            log("pin_low", f"pin={pin} readback={readback.stdout.strip()}")
        except OSError as e:
            log("pin_low_failed", f"pin={pin} error={e}")


def shutdown(procs, log):
    def alive():
        return {n: p for n, p in procs.items() if p.poll() is None}

    live = alive()
    if live:
        for name, p in live.items():
            p.send_signal(signal.SIGINT)
        log("shutdown", f"SIGINT sent to {list(live)}")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and alive():
            time.sleep(0.2)

    live = alive()
    if live:
        for name, p in live.items():
            p.send_signal(signal.SIGTERM)
        log("shutdown", f"SIGTERM sent to {list(live)}")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and alive():
            time.sleep(0.2)

    live = alive()
    if live:
        for name, p in live.items():
            p.kill()
        log("shutdown", f"SIGKILL sent to {list(live)}")

    force_pins_low(log)


def wait_for_first_log(log_dir, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = sorted(log_dir.glob("o3_*.log"))
        if matches:
            return matches[0]
        time.sleep(0.5)
    return None


def supervise(ozone_proc, lamp_proc, deadline_mono, exp_dir, log):
    o3_log_path = wait_for_first_log(exp_dir / "o3logs")
    if o3_log_path is None:
        log("warning", "o3 log file never appeared — RECOVERY/wedge monitoring disabled")

    offset = 0
    last_read_seen = time.monotonic()
    reason = None

    try:
        while time.monotonic() < deadline_mono:
            time.sleep(1)

            if ozone_proc.poll() is not None:
                reason = f"ozone process exited early (code {ozone_proc.returncode})"
                break
            if lamp_proc.poll() is not None:
                reason = f"lamp process exited early (code {lamp_proc.returncode})"
                break

            if o3_log_path is not None and o3_log_path.exists():
                with open(o3_log_path) as f:
                    f.seek(offset)
                    new_text = f.read()
                    offset = f.tell()
                if new_text:
                    if "RECOVERY abandoned" in new_text:
                        reason = "ozone RECOVERY abandoned — controlling failed silently"
                        break
                    if "READ" in new_text:
                        last_read_seen = time.monotonic()
                if time.monotonic() - last_read_seen > 30:
                    reason = "ozone process alive but wedged (no new READ line for >30s)"
                    break
    except KeyboardInterrupt:
        reason = "operator interrupt (Ctrl-C)"

    return reason


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiment_name", help="Directory name under $EXPERIMENTS")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and print resolved commands/layout; spawn nothing, touch no pins")
    args = parser.parse_args()

    experiments_root = os.environ.get("EXPERIMENTS")
    if not experiments_root:
        fail("$EXPERIMENTS is not set. Export it to a directory outside this repo, "
             "e.g. export EXPERIMENTS=/home/bennu/experiments")

    exp_dir = Path(experiments_root) / args.experiment_name
    if not exp_dir.is_dir():
        fail(f"experiment directory does not exist: {exp_dir}")

    real_exp_dir = exp_dir.resolve()
    if real_exp_dir == REPO_ROOT or REPO_ROOT in real_exp_dir.parents:
        fail(f"experiment directory {real_exp_dir} is inside the repo ({REPO_ROOT}) — "
             "experiment data must never re-enter the repo. Point $EXPERIMENTS elsewhere.")

    manifest_path = exp_dir / "manifest.json"
    if not manifest_path.exists():
        fail(f"no manifest.json in {exp_dir}")

    with open(manifest_path) as f:
        manifest = json.load(f)
    validate_manifest(manifest)

    ozone_argv, lamp_argv = build_argv(manifest, exp_dir)
    layout = describe_layout(exp_dir)

    if args.dry_run:
        print("Ozone command:")
        print("  " + " ".join(ozone_argv))
        print("Lamp command:")
        print("  " + " ".join(lamp_argv))
        print()
        print("Planned output layout:")
        print(layout)
        return

    t0_unix = time.time()
    t0_iso = datetime.now().isoformat()
    t0_mono = time.monotonic()

    run_record = {
        "manifest": manifest,
        "ozone_argv": ozone_argv,
        "lamp_argv": lamp_argv,
        "t0_unix": t0_unix,
        "t0_iso": t0_iso,
        "git_rev": get_git_rev(),
        "host": socket.gethostname(),
    }
    with open(exp_dir / "run_record.json", "w") as f:
        json.dump(run_record, f, indent=2)

    runlog_path = exp_dir / "runlog.tsv"
    runlog_file = open(runlog_path, "a")

    def log(event, detail=""):
        line = f"{datetime.now().isoformat(timespec='milliseconds')}\t{event}\t{detail}\n"
        runlog_file.write(line)
        runlog_file.flush()
        print(line, end="")

    log("run_start", f"experiment={args.experiment_name} t0_iso={t0_iso}")

    stdout_ozone = open(exp_dir / "stdout_ozone.log", "w")
    stdout_lamp = open(exp_dir / "stdout_lamp.log", "w")

    ozone_proc = subprocess.Popen(ozone_argv, cwd=exp_dir, stdout=stdout_ozone, stderr=subprocess.STDOUT)
    lamp_proc = subprocess.Popen(lamp_argv, cwd=exp_dir, stdout=stdout_lamp, stderr=subprocess.STDOUT)
    log("spawned", f"ozone_pid={ozone_proc.pid} lamp_pid={lamp_proc.pid}")

    deadline_mono = t0_mono + manifest["duration_min"] * 60
    reason = supervise(ozone_proc, lamp_proc, deadline_mono, exp_dir, log)

    log("shutdown_start", reason or "duration elapsed normally")
    shutdown({"ozone": ozone_proc, "lamp": lamp_proc}, log)
    log("run_end", reason or "completed normally")

    runlog_file.close()
    stdout_ozone.close()
    stdout_lamp.close()

    sys.exit(1 if reason else 0)


if __name__ == "__main__":
    main()
