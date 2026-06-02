import sys
import cv2
import pytesseract
from picamera2 import Picamera2
import time
from collections import Counter

# Tesseract config (digits and period only)
custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.'

class HeuristicFilter:
    def __init__(self, start_val=None, window_duration_sec=1.0, max_delta=1.5, anomaly_threshold=30):
        self.window_duration = window_duration_sec
        self.max_delta = max_delta  
        self.history = []  
        self.last_stable_value = start_val
        
        # Anomaly tracking to handle intentional rapid jumps
        self.consecutive_anomalies = 0
        self.anomaly_threshold = anomaly_threshold # Reset after 30 straight bad reads
        
        if start_val is not None:
            self.history.append((time.time(), start_val))

    def add_reading(self, val):
        """Validates reads, tracks anomalies, and forces a reset if stuck on a real jump."""
        
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
                return  # Reject reading

        # If it passes, reset the anomaly counter and save the valid point
        self.consecutive_anomalies = 0
        self.history.append((time.time(), val))

    def check_for_forced_reset(self, current_rejected_val):
        """If the camera repeatedly sees a new value, accept that the system jumped."""
        if self.consecutive_anomalies >= self.anomaly_threshold:
            if 0.00 <= current_rejected_val <= 50.00:
                print(f"\n[RESET ENGAGED] Grounding shifted to: {current_rejected_val:.2f}\n")
                self.history.clear()
                self.last_stable_value = current_rejected_val
                self.history.append((time.time(), current_rejected_val))
                self.consecutive_anomalies = 0

    def get_stable_value(self):
        """Cleans out old data and returns the most common value from the last second."""
        now = time.time()
        self.history = [(t, v) for t, v in self.history if now - t <= self.window_duration]

        if not self.history:
            return self.last_stable_value

        # Statistical Mode
        values = [round(v, 2) for t, v in self.history]
        counter = Counter(values)
        most_common_val, count = counter.most_common(1)[0]
        
        self.last_stable_value = most_common_val
        return most_common_val


def main():
    if len(sys.argv) != 2:
        print("Error: Missing grounding value.")
        print("Usage: python main.py <initial_value>")
        sys.exit(1)

    try:
        starting_value = float(sys.argv[1])
        if not (0.00 <= starting_value <= 50.00):
            print("Error: Grounding value must be between 0.00 and 50.00.")
            sys.exit(1)
    except ValueError:
        print(f"Error: '{sys.argv[1]}' is not a valid decimal number.")
        sys.exit(1)

    print(f"System successfully grounded at: {starting_value:.2f}")

    # Initialize Camera
    picam2 = Picamera2()
    picam2.preview_configuration.main.size = (640, 480)
    picam2.preview_configuration.main.format = "RGB888"
    picam2.configure("preview")
    picam2.start()
    
    print("Camera feed active. Running stream telemetry...")
    print(f"{'RAW (Fast)':<15} | {'STABLE (Slow)':<15} | {'ANOMALY COUNT'}")
    print("-" * 50)
    
    number_filter = HeuristicFilter(start_val=starting_value, window_duration_sec=1.0, max_delta=1.5)

    while True:
        frame = picam2.capture_array()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        height, width, _ = frame.shape

        # FIXED CROPPING MATRIX: Generous width (from 50% screen) and ample height (35% screen)
        ymin, xmin = 0, max(0, int(width * 0.5))    
        ymax, xmax = int(height * 0.35), width 

        cropped_zone = frame[ymin:ymax, xmin:xmax]
        gray = cv2.cvtColor(cropped_zone, cv2.COLOR_BGR2GRAY)
        
        # Run Tesseract OCR
        detected_text = pytesseract.image_to_string(gray, config=custom_config).strip()

        if detected_text:
            try:
                raw_val = float(detected_text)
                number_filter.add_reading(raw_val)
            except ValueError:
                pass  

        # Extract the filtered consensus
        stable_val = number_filter.get_stable_value()

        # Telemetry log line
        raw_display = detected_text if detected_text else "None"
        stable_display = f"{stable_val:.2f}" if stable_val is not None else "None"
        print(f"{raw_display:<15} | {stable_display:<15} | {number_filter.consecutive_anomalies}")

        # UI bounding box overlays
        cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)
        if stable_val is not None:
            cv2.putText(frame, f"Stable: {stable_val:.2f}", (xmin, ymax + 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        cv2.imshow("Pi Camera Feed", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    picam2.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
