#!/usr/bin/env python3

# sudo apt install -y python3-picamera2 python3-opencv


"""
Detect "big" motion using Picamera2 (libcamera) + OpenCV.


- Prints a message when motion exceeds a configurable fraction of the frame.
- Headless by default (no windows). Add --display to visualize.

Headless (just prints motion events):
python3 big_motion.py

With a live preview and motion mask (handy for tuning thresholds):
python3 big_motion.py --display


Tuning tips
* What counts as “big”: --min-area-pct 2.0 means ~2% of the frame must change. Try 1.0 (more sensitive) or 5.0 (less).

* Sensitivity to small changes: Lower --sensitivity makes it react to smaller differences (e.g., --sensitivity 8.0).

* Stability: Increase --history to make the background model adapt more slowly (useful outdoors).

* Spam control: Increase --cooldown to reduce repeated alerts.

Integrations
If you want it to do something on detection (e.g., write a file, send MQTT, ring a buzzer), drop that code right where the script prints [motion] Big movement detected.

"""


import argparse
import time
from collections import deque


import cv2
import numpy as np
from picamera2 import Picamera2


def parse_args():
    p = argparse.ArgumentParser(
        description="Detect large motion in Raspberry Pi camera feed."
    )
    p.add_argument("--width", type=int, default=640, help="Frame width")
    p.add_argument("--height", type=int, default=480, help="Frame height")
    p.add_argument(
        "--min-area-pct",
        type=float,
        default=2.0,
        help="Min percent of image area that must be moving to trigger (e.g., 2.0 = 2%%)",
    )
    p.add_argument(
        "--cooldown",
        type=float,
        default=2.0,
        help="Seconds to wait between motion alerts",
    )
    p.add_argument(
        "--display",
        action="store_true",
        help="Show a preview window with the motion mask (for debugging)",
    )
    p.add_argument(
        "--warmup",
        type=float,
        default=1.0,
        help="Seconds to allow camera to auto-expose before analysis",
    )
    p.add_argument(
        "--sensitivity",
        type=float,
        default=16.0,
        help="Background subtractor sensitivity (cv2 MOG2 varThreshold). Lower = more sensitive.",
    )
    p.add_argument(
        "--history",
        type=int,
        default=300,
        help="Background history frames (MOG2). Larger = steadier background.",
    )
    return p.parse_args()


def main():
    args = parse_args()


    # Initialize camera
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (args.width, args.height), "format": "RGB888"},
        controls={"FrameRate": 30},
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(args.warmup)


    # Background subtractor (good in variable lighting & small jitters)
    # varThreshold is the squared Mahalanobis distance; lower => more sensitive.
    backsub = cv2.createBackgroundSubtractorMOG2(
        history=args.history, varThreshold=args.sensitivity, detectShadows=True
    )


    # Simple debouncing of detections
    last_alert = 0.0


    # Morphology kernel to clean up noise in the motion mask
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))


    frame_area = args.width * args.height
    min_moving_pixels = int(frame_area * (args.min_area_pct / 100.0))


    # Rolling average of motion area to smooth out spikes
    motion_ema = None
    ema_alpha = 0.2  # 20% new value, 80% old


    # FPS estimation (optional)
    t_times = deque(maxlen=30)


    print(f"[info] Started. Trigger when ~{args.min_area_pct:.2f}% of image moves "
          f"({min_moving_pixels} pixels).")


    try:
        while True:
            t0 = time.time()
            frame = picam2.capture_array()  # RGB888 ndarray
            # Convert to gray for a stable mask (color isn’t needed)
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)


            # Apply background subtraction
            fg = backsub.apply(gray)


            # Remove shadows (MOG2 uses 127 for shadows); keep strong motion only
            _, fg_bin = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)


            # Morphological cleanup
            fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_OPEN, kernel, iterations=1)
            fg_bin = cv2.dilate(fg_bin, kernel, iterations=2)


            moving_pixels = int(cv2.countNonZero(fg_bin))


            # Smooth with EMA to avoid flicker
            if motion_ema is None:
                motion_ema = float(moving_pixels)
            else:
                motion_ema = ema_alpha * moving_pixels + (1 - ema_alpha) * motion_ema


            # Decide if "big motion" happened
            big_motion = motion_ema >= min_moving_pixels
            now = time.time()
            if big_motion and (now - last_alert) >= args.cooldown:
                pct = (motion_ema / frame_area) * 100.0
                print(f"[motion] Big movement detected: ~{pct:.1f}% of frame at {time.strftime('%H:%M:%S')}")
                last_alert = now


            if args.display:
                # Overlay simple HUD
                disp = frame.copy()
                cv2.putText(
                    disp,
                    f"Moving ~{(motion_ema/frame_area)*100:.1f}% | threshold {args.min_area_pct:.1f}%",
                    (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.imshow("Camera", cv2.cvtColor(disp, cv2.COLOR_RGB2BGR))
                cv2.imshow("Motion mask", fg_bin)


                # Exit on q
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break


            # Simple FPS estimate (optional, no print spam)
            t_times.append(time.time() - t0)


    except KeyboardInterrupt:
        pass
    finally:
        picam2.stop()
        if args.display:
            cv2.destroyAllWindows()
        print("[info] Stopped.")


if __name__ == "__main__":
    main()
    
