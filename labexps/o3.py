"""Read a numeric display with the Pi camera and hold its level with GPIO pulses.

Each pass of the main loop does the same six things:

    capture frame -> crop to the OCR box -> Tesseract -> filter the reading
    -> decide whether to tickle -> report to stdout, the log and the preview

The display is a numeric readout (ozone ppm in the lab rig). OCR of a small,
low-contrast seven-segment display is noisy, so raw reads are never trusted
directly. HeuristicFilter keeps a "grounding" value -- its best idea of the
current true level -- and rejects reads that disagree with it too much, then
reports the statistical mode over a one-second sliding window as the stable
value. The loop acts only on that stable value.

Control is one-directional: pulsing the GPIO pin ("tickling") drives the level
up, and nothing drives it down but time. So the loop only ever decides whether
to pulse, and it does so when the stable value falls below a threshold.

There are two modes:

    normal    Tickle whenever the stable value is below --tickle-low-threshold,
              no more often than --tickle-delay-ms. This holds the level just
              above the threshold.

    RECOVER   Ignore the threshold and keep tickling until the level is back at
              --target, spacing pulses --recovery-tickle-delay-ms apart.

RECOVER exists because the grounding can go stale. If OCR fails for a long
stretch, nothing updates the grounding while the real level falls. When OCR
comes back, the correct low reads are now far from the stale grounding, so the
filter rejects them as anomalies, keeps reporting the stale value, sees nothing
below the threshold, and stops tickling while the level keeps falling -- a
declining spiral with no way out. The filter detects this by noticing a long
run of rejections that ends in several reads agreeing with each other, which
means the display moved rather than that the reads are bad, and re-grounds onto
that cluster. If the true level turns out to be below --target, RECOVER climbs
back to it. A pulse budget that only refills on a new high stops a dead
generator or an unreadable display from being tickled forever.

Outputs: a per-frame table on stdout, a per-run log under o3logs/ (see the
README for the line format), and an upscaled preview window showing the OCR box.
"""

import sys
import os
import cv2
import pytesseract
from picamera2 import Picamera2
import time
import threading
import argparse
from collections import Counter
from datetime import datetime

# GPIO is Pi-only. Import failure is not fatal: the program still runs as a
# read-only monitor, and only the tickling options are refused.
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Capture and OCR geometry
# ---------------------------------------------------------------------------

# Tesseract config (digits and period only)
custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.'

LOG_DIR = os.path.join(os.path.dirname(__file__), 'o3logs')

# Native size of the camera preview frame the OCR crop box is drawn within.
FRAME_W, FRAME_H = 160, 120

# The native frame is too small to see clearly on screen, so the display
# window (both normal running and --calibrate) is shown upscaled by this
# factor. OCR itself still runs on the native-resolution frame.
DISPLAY_SCALE = 4

# Original hardcoded crop box (top-right corner of the frame), preserved here
# only to derive the default --vidpos extent (same size, but centered).
_DEFAULT_CROP_W = int(FRAME_W * 0.30)
_DEFAULT_CROP_H = int(FRAME_H * 0.20)


def parse_vidpos(s):
    """Parse a --vidpos value of the form '[x1,y1,x2,y2]' (brackets optional).

    Defines the OCR crop box within the video frame: top-left-x, top-left-y,
    bottom-right-x, bottom-right-y, in frame pixel coordinates.
    """
    parts = [p.strip() for p in s.strip().strip('[]').split(',')]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--vidpos must be 4 comma-separated integers: top-left-x,top-left-y,bottom-right-x,bottom-right-y")
    try:
        x1, y1, x2, y2 = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError("--vidpos values must be integers")
    if x2 <= x1 or y2 <= y1:
        raise argparse.ArgumentTypeError("--vidpos bottom-right corner must be greater than top-left corner")
    if x1 < 0 or y1 < 0 or x2 > FRAME_W or y2 > FRAME_H:
        raise argparse.ArgumentTypeError(
            f"--vidpos must fit within the {FRAME_W}x{FRAME_H} frame")
    return [x1, y1, x2, y2]


def default_vidpos():
    """Crop box used when neither --vidpos nor --calibrate is given.

    Hardcoded to the box that suits the current rig rather than computed. The
    centered-box calculation it replaced is kept below, commented out, as the
    right starting point if the camera is ever repositioned.
    """
    return [50, 70, 110, 95]
    # x1 = (FRAME_W - _DEFAULT_CROP_W) // 2
    # y1 = (FRAME_H - _DEFAULT_CROP_H) // 2
    # return [x1, y1, x1 + _DEFAULT_CROP_W, y1 + _DEFAULT_CROP_H]


# ---------------------------------------------------------------------------
# Interactive crop-box calibration
# ---------------------------------------------------------------------------

def run_calibration(picam2):
    """Show an upscaled live feed and let the user drag a box with the mouse
    to pick the OCR crop region. Returns [x1,y1,x2,y2] in native frame pixel
    coordinates, or None if the user cancelled.
    """
    window = "Calibrate OCR box: drag to select, 'c'=confirm 'r'=reset 'q'=cancel"
    cv2.namedWindow(window)
    drag = {"active": False, "start": None, "box": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            drag["active"] = True
            drag["start"] = (x, y)
            drag["box"] = None
        elif event == cv2.EVENT_MOUSEMOVE and drag["active"]:
            x0, y0 = drag["start"]
            drag["box"] = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
        elif event == cv2.EVENT_LBUTTONUP and drag["active"]:
            drag["active"] = False
            x0, y0 = drag["start"]
            drag["box"] = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))

    cv2.setMouseCallback(window, on_mouse)

    result = None
    try:
        while True:
            frame = picam2.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            display = cv2.resize(frame, (FRAME_W * DISPLAY_SCALE, FRAME_H * DISPLAY_SCALE),
                                  interpolation=cv2.INTER_NEAREST)

            if drag["box"]:
                dx1, dy1, dx2, dy2 = drag["box"]
                cv2.rectangle(display, (dx1, dy1), (dx2, dy2), (0, 0, 255), 2)

            cv2.putText(display, "drag a box around the digits  |  c=confirm  r=reset  q=cancel",
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.imshow(window, display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('r'):
                drag["box"] = None
            elif key == ord('c') and drag["box"]:
                dx1, dy1, dx2, dy2 = drag["box"]
                x1 = max(0, dx1 // DISPLAY_SCALE)
                y1 = max(0, dy1 // DISPLAY_SCALE)
                x2 = min(FRAME_W, -(-dx2 // DISPLAY_SCALE))  # ceil div
                y2 = min(FRAME_H, -(-dy2 // DISPLAY_SCALE))
                if x2 > x1 and y2 > y1:
                    result = [x1, y1, x2, y2]
                    break
            elif key == ord('q'):
                break
    finally:
        cv2.destroyWindow(window)

    return result


# ---------------------------------------------------------------------------
# Reading filter
# ---------------------------------------------------------------------------

class HeuristicFilter:
    """Turn a stream of noisy OCR reads into a trustworthy level.

    The filter holds a *grounding* value (last_stable_value): its current best
    idea of the true level. Every new read is judged against it by three rules,
    applied in order by add_reading:

        1. Decimal recovery -- a read above the 50.00 ceiling is usually a lost
           decimal point, so try it divided by 10 and by 100 and keep whichever
           lands near the grounding.
        2. Range -- anything outside 0.00-50.00 is impossible; reject it.
        3. Rate of change -- reject a read further than max_delta from the
           grounding. Reads that land exactly on a whole number get a tighter
           0.3 allowance, because a dropped decimal point ("30" for "3.0") is a
           common OCR failure and looks plausible otherwise.

    Accepted reads go into a time-boxed history; get_stable_value reports the
    mode of the last window_duration seconds, so a single bad read that slips
    through cannot move the reported value.

    Rejecting is the safe default for noise, but it fails when the grounding
    itself is wrong: correct reads then look anomalous and are rejected
    indefinitely. Two escapes exist. check_for_forced_reset re-grounds after
    anomaly_threshold consecutive rejections using the single triggering read.
    check_for_confirmed_reground waits for stronger evidence -- a long
    rejection run ending in several reads that agree with each other -- and is
    tried first. Either way on_reset fires so the caller can react.
    """

    def __init__(self, start_val=None, window_duration_sec=1.0, max_delta=1.5,
                 anomaly_threshold=30, on_reset=None,
                 stuck_anomaly_count=25, recovery_confirm_count=10):
        self.window_duration = window_duration_sec
        self.max_delta = max_delta
        self.history = []
        self.last_stable_value = start_val
        self.consecutive_anomalies = 0
        self.anomaly_threshold = anomaly_threshold  # None means never force-reset
        self.on_reset = on_reset  # callback(new_val, reason) fired on any re-ground

        # Stuck-grounding detection. If OCR fails for a long time the real level
        # can drift far from the grounding value; when OCR recovers, the correct
        # readings then look like anomalies and get rejected forever, so the
        # filter reports a stale value and the loop stops tickling. A long run of
        # rejections followed by a tight cluster of mutually consistent readings
        # is the signature of "the display moved, our grounding is stale" rather
        # than of noise, so re-ground onto the cluster.
        self.stuck_anomaly_count = stuck_anomaly_count
        self.recovery_confirm_count = recovery_confirm_count
        self.pending = []  # in-range values rejected against the current grounding

        if start_val is not None:
            self.history.append((time.time(), start_val))

    def add_reading(self, val):
        """Judge one OCR read and either accept it into history or reject it.

        Rejections are counted, and plausible ones are remembered as evidence
        that the grounding may be stale. Nothing is returned; call
        get_stable_value for the filtered level.
        """
        # 1. Smart Decimal Recovery
        if val > 50.00 and self.last_stable_value is not None:
            if abs((val / 10.0) - self.last_stable_value) <= self.max_delta:
                val = val / 10.0
            elif abs((val / 100.0) - self.last_stable_value) <= self.max_delta:
                val = val / 100.0

        # 2. Hard Range Constraints
        if not (0.00 <= val <= 50.00):
            self.consecutive_anomalies += 1
            self.check_for_forced_reset(val)
            return

        # 3. Enhanced Rate of Change & Whole Integer Check
        if self.last_stable_value is not None:
            is_whole_integer = (val % 1.0 == 0.0)
            allowed_gap = 0.3 if is_whole_integer else self.max_delta

            if abs(val - self.last_stable_value) > allowed_gap:
                self.consecutive_anomalies += 1
                # Remember rejected but physically plausible readings; a run of
                # them agreeing with each other is what proves the grounding
                # stale rather than the readings bad.
                self.pending.append(val)
                if len(self.pending) > self.recovery_confirm_count:
                    del self.pending[:-self.recovery_confirm_count]
                # Prefer the corroborated re-ground over the single-value forced
                # reset: it takes more evidence, so it is far less likely to
                # ground onto a garbage read.
                if self.check_for_confirmed_reground():
                    return
                self.check_for_forced_reset(val)
                return

        self.consecutive_anomalies = 0
        self.pending.clear()
        self.history.append((time.time(), val))

    def check_for_confirmed_reground(self):
        """Re-ground after a long run of rejections that ends in agreement.

        Requires both a long enough rejection run and the last
        recovery_confirm_count rejected readings to sit within max_delta of each
        other. Returns True if a re-ground happened.
        """
        if self.consecutive_anomalies < self.stuck_anomaly_count:
            return False
        if len(self.pending) < self.recovery_confirm_count:
            return False
        cluster = self.pending[-self.recovery_confirm_count:]
        if max(cluster) - min(cluster) > self.max_delta:
            return False
        new_val = sorted(cluster)[len(cluster) // 2]  # median resists one stray read
        print(f"\n[STUCK GROUNDING] {self.consecutive_anomalies} rejects then "
              f"{len(cluster)} agreeing reads — re-grounding to: {new_val:.2f}\n")
        self._reground(new_val, 'confirmed')
        return True

    def check_for_forced_reset(self, current_rejected_val):
        """Re-ground on the triggering read after too many rejections in a row.

        The blunt escape hatch: it trusts a single read, so it can ground onto a
        garbage value. --forced-reset-count never disables it, which is the
        usual setting, leaving check_for_confirmed_reground to do this job on
        better evidence.
        """
        if self.anomaly_threshold is None:
            return
        if self.consecutive_anomalies >= self.anomaly_threshold:
            if 0.00 <= current_rejected_val <= 50.00:
                print(f"\n[RESET ENGAGED] Grounding shifted to: {current_rejected_val:.2f}\n")
                self._reground(current_rejected_val, 'forced')

    def _reground(self, new_val, reason):
        """Move the grounding to new_val and discard everything based on the old one.

        History and pending evidence both refer to the previous grounding, so
        they are cleared rather than carried over. reason is 'forced' or
        'confirmed' and is passed on to the on_reset callback.
        """
        self.history.clear()
        self.last_stable_value = new_val
        self.history.append((time.time(), new_val))
        self.consecutive_anomalies = 0
        self.pending.clear()
        if self.on_reset:
            self.on_reset(new_val, reason)

    def get_stable_value(self):
        """Report the mode of the accepted reads inside the sliding window.

        The mode, not the mean, so one outlier that passed the rules cannot drag
        the answer. When the window is empty -- OCR failing, or every read being
        rejected -- the last known value is returned unchanged, which is what
        makes a stale grounding possible and why the re-ground checks exist.
        """
        now = time.time()
        self.history = [(t, v) for t, v in self.history if now - t <= self.window_duration]

        if not self.history:
            return self.last_stable_value

        values = [round(v, 2) for t, v in self.history]
        counter = Counter(values)
        most_common_val, _ = counter.most_common(1)[0]

        self.last_stable_value = most_common_val
        return most_common_val


# ---------------------------------------------------------------------------
# Command line, setup and the control loop
# ---------------------------------------------------------------------------

def main():
    """Parse arguments, set up camera/GPIO/logging, then run the control loop.

    Laid out in order: arguments, optional interactive calibration, validation,
    log file, camera, recovery state and pulse machinery, then the loop itself.
    Everything the loop needs lives in closures over this function's locals, so
    the run's configuration is fixed by the time the loop starts.
    """
    parser = argparse.ArgumentParser(description="OCR a numeric display via Pi camera and monitor its level.")
    parser.add_argument("initial_value", type=float,
                        help="Grounding value to seed the filter (0.00-50.00)")
    parser.add_argument("--forced-reset-count", "-frc", default="30",
                        help="Consecutive anomalies before forced re-ground, or 'never' to disable (default: 30)")
    parser.add_argument("--gpiopin", type=int, default=None,
                        help="BCM GPIO pin to pulse when value drops below --tickle-low-threshold")
    parser.add_argument("--gpio-ms", type=int, default=500,
                        help="Duration in milliseconds to hold GPIO pin high (default: 500)")
    parser.add_argument("--tickle-low-threshold", "-tlt", type=float, default=None,
                        help="Pulse GPIO pin whenever stable value drops below this level")
    parser.add_argument("--max-delta", "-md", type=float, default=1.5,
                        help="Max allowed change between readings before rejection (default: 1.5)")
    parser.add_argument("--tickle-delay-ms", "-tdms", type=int, default=5000,
                        help="Minimum milliseconds between tickle pulses (default: 5000)")
    parser.add_argument("--target", "-t", type=float, default=None,
                        help="Normal operating level. Only used for recovery: after the level has "
                             "been found stuck below --tickle-low-threshold, tickling continues up "
                             "to this level instead of stopping at the threshold. "
                             "(default: the initial grounding value)")
    parser.add_argument("--stuck-anomaly-count", "-sac", type=int, default=25,
                        help="Consecutive rejected readings that mark OCR as having failed for a "
                             "long time, arming stuck-grounding detection (default: 25)")
    parser.add_argument("--recovery-confirm-count", "-rcc", type=int, default=10,
                        help="Consecutive rejected-but-agreeing readings required to accept a new "
                             "grounding once stuck detection is armed (default: 10)")
    parser.add_argument("--recovery-tickle-delay-ms", "-rtdms", type=int, default=None,
                        help="Minimum milliseconds between tickle pulses while recovering, kept "
                             "longer than normal so the measurement catches up between pulses "
                             "(default: 2x --tickle-delay-ms)")
    parser.add_argument("--recovery-max-pulses", "-rmp", type=int, default=20,
                        help="Safety cap: tickle pulses allowed during recovery without the level "
                             "reaching a new high. Any new high refills the budget, so this only "
                             "trips when tickling is achieving nothing, and recovery is then "
                             "abandoned rather than tickling blindly (default: 20)")
    parser.add_argument("--vidpos", type=parse_vidpos, default=None,
                        help="OCR crop box within the video frame, as "
                             "[top-left-x,top-left-y,bottom-right-x,bottom-right-y] e.g. --vidpos [100,20,150,40]. "
                             f"Coordinates are in {FRAME_W}x{FRAME_H} frame pixels. "
                             "Default: same size as the original crop region, but centered in the frame.")
    parser.add_argument("--calibrate", action="store_true",
                        help="Open an upscaled live feed and drag a box with the mouse to pick the OCR crop "
                             "region interactively (overrides --vidpos). Prints the resulting --vidpos value "
                             "to reuse next time without recalibrating.")
    args = parser.parse_args()

    if args.calibrate:
        calib_cam = Picamera2()
        calib_cam.preview_configuration.main.size = (FRAME_W, FRAME_H)
        calib_cam.preview_configuration.main.format = "RGB888"
        calib_cam.configure("preview")
        calib_cam.start()
        calibrated = run_calibration(calib_cam)
        calib_cam.stop()
        cv2.destroyAllWindows()
        if calibrated is None:
            print("Calibration cancelled.")
            sys.exit(0)
        args.vidpos = calibrated
        print(f"Calibrated OCR crop box: {args.vidpos}")
        print(f"  Reuse without recalibrating: --vidpos {args.vidpos[0]},{args.vidpos[1]},{args.vidpos[2]},{args.vidpos[3]}")
        print()
    elif args.vidpos is None:
        args.vidpos = default_vidpos()

    # Validate initial value
    if not (0.00 <= args.initial_value <= 50.00):
        print("Error: Grounding value must be between 0.00 and 50.00.")
        sys.exit(1)

    # The normal operating level defaults to whatever we were grounded at.
    if args.target is None:
        args.target = args.initial_value
    if not (0.00 <= args.target <= 50.00):
        print("Error: --target must be between 0.00 and 50.00.")
        sys.exit(1)
    if args.recovery_tickle_delay_ms is None:
        args.recovery_tickle_delay_ms = args.tickle_delay_ms * 2
    if args.stuck_anomaly_count < 1 or args.recovery_confirm_count < 1:
        print("Error: --stuck-anomaly-count and --recovery-confirm-count must be at least 1.")
        sys.exit(1)

    # Parse forced-reset-count
    frc = args.forced_reset_count.strip().lower()
    if frc == "never":
        anomaly_threshold = None
    else:
        try:
            anomaly_threshold = int(frc)
        except ValueError:
            print(f"Error: --forced-reset-count must be an integer or 'never', got '{args.forced_reset_count}'")
            sys.exit(1)

    # Validate GPIO args — both required together
    gpio_active = args.gpiopin is not None and args.tickle_low_threshold is not None
    if (args.gpiopin is None) != (args.tickle_low_threshold is None):
        print("Error: --gpiopin and --tickle-low-threshold (-tlt) must be specified together.")
        sys.exit(1)
    if gpio_active and args.target < args.tickle_low_threshold:
        print(f"Error: --target ({args.target}) must not be below --tickle-low-threshold "
              f"({args.tickle_low_threshold}); recovery would drive the level down.")
        sys.exit(1)
    if gpio_active and not GPIO_AVAILABLE:
        print("Error: RPi.GPIO is not available on this system.")
        sys.exit(1)
    if gpio_active:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(args.gpiopin, GPIO.OUT, initial=GPIO.LOW)

    # Open log file
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(LOG_DIR, f'o3_{ts}.log')
    log_lock = threading.Lock()

    def log(msg):
        line = f"{datetime.now().isoformat(timespec='milliseconds')}  {msg}\n"
        with log_lock:
            log_file.write(line)
            log_file.flush()

    with open(log_path, 'w') as log_file:
        # Write run header
        frc_display = 'never' if anomaly_threshold is None else str(anomaly_threshold)
        log_file.write(f"# o3 run started: {datetime.now().isoformat()}\n")
        log_file.write(f"# initial_value={args.initial_value}  max_delta={args.max_delta}"
                       f"  forced_reset_count={frc_display}  target={args.target}\n")
        if gpio_active:
            log_file.write(f"# gpio: pin={args.gpiopin}  ms={args.gpio_ms}"
                           f"  tickle_low_threshold={args.tickle_low_threshold}"
                           f"  tickle_delay_ms={args.tickle_delay_ms}\n")
        log_file.write(f"# recovery: stuck_anomaly_count={args.stuck_anomaly_count}"
                       f"  recovery_confirm_count={args.recovery_confirm_count}"
                       f"  recovery_tickle_delay_ms={args.recovery_tickle_delay_ms}"
                       f"  recovery_max_pulses={args.recovery_max_pulses}\n")
        log_file.write(f"# vidpos={args.vidpos}\n")
        log_file.write("#\n")
        log_file.write("# timestamp                     event\n")
        log_file.write("#" + "-" * 70 + "\n")
        log_file.flush()

        # Startup summary to stdout
        print(f"Grounded at:     {args.initial_value:.2f}")
        print(f"Forced reset:    {'disabled' if anomaly_threshold is None else f'after {anomaly_threshold} anomalies'}")
        print(f"Normal target:   {args.target:.2f}")
        if gpio_active:
            print(f"GPIO tickle:     pin {args.gpiopin}, {args.gpio_ms} ms pulse when value < {args.tickle_low_threshold:.2f}")
            print(f"Tickle delay:    {args.tickle_delay_ms} ms minimum between pulses")
            print(f"Recovery:        arm after {args.stuck_anomaly_count} rejects, confirm with "
                  f"{args.recovery_confirm_count} agreeing reads, climb to {args.target:.2f} "
                  f"at {args.recovery_tickle_delay_ms} ms spacing, max {args.recovery_max_pulses} pulses")
        print(f"OCR crop box:    {args.vidpos}")
        print(f"Log:             {log_path}")
        print()

        # Initialize Camera
        picam2 = Picamera2()
        picam2.preview_configuration.main.size = (160, 120)
        picam2.preview_configuration.main.format = "RGB888"
        picam2.configure("preview")
        picam2.start()

        print("Camera feed active. Running stream telemetry...")
        print(f"{'RAW (Fast)':<15} | {'STABLE (Slow)':<15} | {'TARGET':<10} | {'MODE':<8} | {'ANOMALIES':<10} | TICKLE")
        print("-" * 90)

        # Recovery state. While active the min tickle point is ignored and the
        # loop drives all the way back to args.target, with pulses spaced wider
        # apart and capped so a broken display can never mean blind tickling.
        recovery = {"active": False, "pulses": 0, "best": None}

        def enter_recovery(from_val, reason):
            already = recovery["active"]
            recovery["active"] = True
            # A corroborated re-ground is fresh evidence of where we actually
            # are, so it earns a full pulse budget. A single-value forced reset
            # does not, or a flapping display could refill the budget forever.
            if not already or reason == 'confirmed':
                recovery["pulses"] = 0
                recovery["best"] = from_val
            if already:
                return
            print(f"\n[RECOVERY ENGAGED] {from_val:.2f} is below target {args.target:.2f} — "
                  f"ignoring tickle threshold {args.tickle_low_threshold:.2f} "
                  f"and climbing back to target\n")
            log(f"RECOVERY start  from={from_val:.2f}  target={args.target:.2f}  reason={reason}")

        def on_reground(new_val, reason):
            log(f"RESET  new_ground={new_val:.2f}  reason={reason}")
            # Re-grounding is the moment we learn the true level. If that is
            # below target, the run has been sitting low while we reported a
            # stale value, which is exactly the declining spiral to climb out of.
            if gpio_active and new_val < args.target:
                enter_recovery(new_val, reason)

        number_filter = HeuristicFilter(
            start_val=args.initial_value,
            window_duration_sec=1.0,
            max_delta=args.max_delta,
            anomaly_threshold=anomaly_threshold,
            on_reset=on_reground,
            stuck_anomaly_count=args.stuck_anomaly_count,
            recovery_confirm_count=args.recovery_confirm_count,
        )

        # GPIO pulse state — prevents overlapping pulses and enforces tickle-delay-ms
        pulse_lock = threading.Lock()
        pulse_active = [False]
        last_pulse_end_time = [0.0]

        def do_pulse():
            GPIO.output(args.gpiopin, GPIO.HIGH)
            log(f"GPIO   pin={args.gpiopin}  state=HIGH  duration_ms={args.gpio_ms}")
            time.sleep(args.gpio_ms / 1000.0)
            GPIO.output(args.gpiopin, GPIO.LOW)
            log(f"GPIO   pin={args.gpiopin}  state=LOW")
            with pulse_lock:
                last_pulse_end_time[0] = time.time()
                pulse_active[0] = False

        try:
            # One iteration per camera frame. In order: read the display, filter
            # the reading, update recovery state, decide whether to tickle, then
            # report the same facts to stdout, the log and the preview window.
            # 'q' in the preview window quits; the finally block always releases
            # the camera and the GPIO pin.
            while True:
                # --- read the display ---
                frame = picam2.capture_array()
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                xmin, ymin, xmax, ymax = args.vidpos

                cropped_zone = frame[ymin:ymax, xmin:xmax]
                gray = cv2.cvtColor(cropped_zone, cv2.COLOR_BGR2GRAY)

                detected_text = pytesseract.image_to_string(gray, config=custom_config).strip()

                if detected_text:
                    try:
                        number_filter.add_reading(float(detected_text))
                    except ValueError:
                        pass

                stable_val = number_filter.get_stable_value()

                # --- update recovery state ---
                # Climbing is working: a new high means the pulses are landing, so
                # refill the budget. The cap therefore measures pulses that
                # achieved nothing, not total effort spent on a slow rise.
                if (recovery["active"] and stable_val is not None
                        and recovery["best"] is not None and stable_val > recovery["best"]):
                    recovery["best"] = stable_val
                    recovery["pulses"] = 0

                # Recovery exits on success, or on spending the budget with no
                # progress, so a display we cannot actually influence never
                # leaves the loop tickling indefinitely.
                if recovery["active"] and stable_val is not None and stable_val >= args.target:
                    recovery["active"] = False
                    print(f"\n[RECOVERY COMPLETE] back at target {args.target:.2f}\n")
                    log(f"RECOVERY done  stable={stable_val:.2f}")
                elif recovery["active"] and recovery["pulses"] >= args.recovery_max_pulses:
                    recovery["active"] = False
                    best = recovery["best"]
                    print(f"\n[RECOVERY ABANDONED] {recovery['pulses']} pulses with no new high "
                          f"(best {best:.2f} of target {args.target:.2f}) — "
                          f"check the generator and the OCR box\n")
                    log(f"RECOVERY abandoned  pulses={recovery['pulses']}  best={best:.2f}"
                        f"  target={args.target:.2f}")

                # In recovery the min tickle point is ignored: drive to the target
                # instead of stopping at the threshold, with wider pulse spacing.
                if recovery["active"]:
                    effective_threshold = args.target
                    effective_delay_ms = args.recovery_tickle_delay_ms
                else:
                    effective_threshold = args.tickle_low_threshold
                    effective_delay_ms = args.tickle_delay_ms

                # Tickle: pulse GPIO if stable value is below threshold and no pulse is running
                tickled = False
                delay_elapsed = (time.time() - last_pulse_end_time[0]) >= (effective_delay_ms / 1000.0)
                if gpio_active and stable_val is not None and stable_val < effective_threshold and delay_elapsed:
                    with pulse_lock:
                        if not pulse_active[0]:
                            pulse_active[0] = True
                            tickled = True
                            if recovery["active"]:
                                recovery["pulses"] += 1
                            threading.Thread(target=do_pulse, daemon=True).start()

                # --- report: stdout table, log line, preview window ---
                raw_display = detected_text if detected_text else "None"
                stable_display = f"{stable_val:.2f}" if stable_val is not None else "None"
                tickle_display = "*** TICKLE ***" if tickled else ""
                target_display = (f"{effective_threshold:.2f}"
                                  if effective_threshold is not None else "none")
                mode_display = "RECOVER" if recovery["active"] else "normal"

                log(f"READ   raw={raw_display:<10}  stable={stable_display:<8}"
                    f"  target={target_display:<8}  mode={mode_display:<8}"
                    f"  anomalies={number_filter.consecutive_anomalies}"
                    + (f"  TICKLE" if tickled else ""))

                print(f"{raw_display:<15} | {stable_display:<15} | {target_display:<10} | {mode_display:<8} | {number_filter.consecutive_anomalies:<10} | {tickle_display}")

                display = cv2.resize(frame, (FRAME_W * DISPLAY_SCALE, FRAME_H * DISPLAY_SCALE),
                                      interpolation=cv2.INTER_NEAREST)
                dxmin, dymin = xmin * DISPLAY_SCALE, ymin * DISPLAY_SCALE
                dxmax, dymax = xmax * DISPLAY_SCALE, ymax * DISPLAY_SCALE

                cv2.rectangle(display, (dxmin, dymin), (dxmax, dymax), (0, 0, 255), 2)
                if stable_val is not None:
                    cv2.putText(display, f"Stable: {stable_val:.2f}", (dxmin, dymax + 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                if tickled:
                    cv2.putText(display, "TICKLE!", (dxmin, dymax + 45),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                if recovery["active"]:
                    cv2.putText(display, f"RECOVERY -> {args.target:.2f}",
                                (dxmin, max(dymin - 8, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

                cv2.imshow("Pi Camera Feed", display)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

        finally:
            picam2.stop()
            cv2.destroyAllWindows()
            if gpio_active:
                GPIO.cleanup()
            log(f"# run ended: {datetime.now().isoformat()}")
            print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    main()
