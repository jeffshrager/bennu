import sys
import cv2
import pytesseract
from picamera2 import Picamera2
import time
import threading
import argparse
from collections import Counter

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

# Tesseract config (digits and period only)
custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.'


class HeuristicFilter:
    def __init__(self, start_val=None, window_duration_sec=1.0, max_delta=1.5, anomaly_threshold=30):
        self.window_duration = window_duration_sec
        self.max_delta = max_delta
        self.history = []
        self.last_stable_value = start_val

        self.consecutive_anomalies = 0
        self.anomaly_threshold = anomaly_threshold  # None means never force-reset

        if start_val is not None:
            self.history.append((time.time(), start_val))

    def add_reading(self, val):
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
                self.check_for_forced_reset(val)
                return

        self.consecutive_anomalies = 0
        self.history.append((time.time(), val))

    def check_for_forced_reset(self, current_rejected_val):
        if self.anomaly_threshold is None:
            return
        if self.consecutive_anomalies >= self.anomaly_threshold:
            if 0.00 <= current_rejected_val <= 50.00:
                print(f"\n[RESET ENGAGED] Grounding shifted to: {current_rejected_val:.2f}\n")
                self.history.clear()
                self.last_stable_value = current_rejected_val
                self.history.append((time.time(), current_rejected_val))
                self.consecutive_anomalies = 0

    def get_stable_value(self):
        now = time.time()
        self.history = [(t, v) for t, v in self.history if now - t <= self.window_duration]

        if not self.history:
            return self.last_stable_value

        values = [round(v, 2) for t, v in self.history]
        counter = Counter(values)
        most_common_val, _ = counter.most_common(1)[0]

        self.last_stable_value = most_common_val
        return most_common_val


def main():
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
    args = parser.parse_args()

    # Validate initial value
    if not (0.00 <= args.initial_value <= 50.00):
        print("Error: Grounding value must be between 0.00 and 50.00.")
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
    if gpio_active and not GPIO_AVAILABLE:
        print("Error: RPi.GPIO is not available on this system.")
        sys.exit(1)
    if gpio_active:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(args.gpiopin, GPIO.OUT, initial=GPIO.LOW)

    # Startup summary
    print(f"Grounded at:     {args.initial_value:.2f}")
    print(f"Forced reset:    {'disabled' if anomaly_threshold is None else f'after {anomaly_threshold} anomalies'}")
    if gpio_active:
        print(f"GPIO tickle:     pin {args.gpiopin}, {args.gpio_ms} ms pulse when value < {args.tickle_low_threshold:.2f}")
    print()

    # Initialize Camera
    picam2 = Picamera2()
    picam2.preview_configuration.main.size = (640, 480)
    picam2.preview_configuration.main.format = "RGB888"
    picam2.configure("preview")
    picam2.start()

    print("Camera feed active. Running stream telemetry...")
    print(f"{'RAW (Fast)':<15} | {'STABLE (Slow)':<15} | {'ANOMALIES':<10} | TICKLE")
    print("-" * 60)

    number_filter = HeuristicFilter(
        start_val=args.initial_value,
        window_duration_sec=1.0,
        max_delta=args.max_delta,
        anomaly_threshold=anomaly_threshold,
    )

    # GPIO pulse state — prevents overlapping pulses
    pulse_lock = threading.Lock()
    pulse_active = [False]

    def do_pulse():
        GPIO.output(args.gpiopin, GPIO.HIGH)
        time.sleep(args.gpio_ms / 1000.0)
        GPIO.output(args.gpiopin, GPIO.LOW)
        with pulse_lock:
            pulse_active[0] = False

    try:
        while True:
            frame = picam2.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            height, width, _ = frame.shape

            ymin, xmin = 0, max(0, int(width * 0.5))
            ymax, xmax = int(height * 0.35), width

            cropped_zone = frame[ymin:ymax, xmin:xmax]
            gray = cv2.cvtColor(cropped_zone, cv2.COLOR_BGR2GRAY)

            detected_text = pytesseract.image_to_string(gray, config=custom_config).strip()

            if detected_text:
                try:
                    number_filter.add_reading(float(detected_text))
                except ValueError:
                    pass

            stable_val = number_filter.get_stable_value()

            # Tickle: pulse GPIO if stable value is below threshold and no pulse is already running
            tickled = False
            if gpio_active and stable_val is not None and stable_val < args.tickle_low_threshold:
                with pulse_lock:
                    if not pulse_active[0]:
                        pulse_active[0] = True
                        tickled = True
                        threading.Thread(target=do_pulse, daemon=True).start()

            raw_display = detected_text if detected_text else "None"
            stable_display = f"{stable_val:.2f}" if stable_val is not None else "None"
            tickle_display = "*** TICKLE ***" if tickled else ""
            print(f"{raw_display:<15} | {stable_display:<15} | {number_filter.consecutive_anomalies:<10} | {tickle_display}")

            cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)
            if stable_val is not None:
                cv2.putText(frame, f"Stable: {stable_val:.2f}", (xmin, ymax + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            if tickled:
                cv2.putText(frame, "TICKLE!", (xmin, ymax + 45),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            cv2.imshow("Pi Camera Feed", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        picam2.stop()
        cv2.destroyAllWindows()
        if gpio_active:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
