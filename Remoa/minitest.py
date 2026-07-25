#!/usr/bin/env python3
import time
import RPi.GPIO as GPIO

from adc_sensors import read_current

# ------------------------------
# Lamp configuration
# ------------------------------

QUAD_GPIO_PINS = {
    "bowport":   16,
    "bowstar":   23,
    "sternport": 24,
    "sternstar": 25,
}

ORDER = ["bowport", "bowstar", "sternport", "sternstar"]


# ------------------------------
# GPIO setup helpers
# ------------------------------

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for pin in QUAD_GPIO_PINS.values():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

def all_off():
    for pin in QUAD_GPIO_PINS.values():
        GPIO.output(pin, GPIO.LOW)


# ------------------------------
# Main micro-test
# ------------------------------

def main():
    print("\n=== MICRO CURRENT/LAMP TEST ===\n")
    setup_gpio()
    all_off()

    active = []

    for quad in ORDER:
        print(f"\n--- Turning ON: {quad} ---")
        active.append(quad)

        # Turn on current set
        for q, pin in QUAD_GPIO_PINS.items():
            GPIO.output(pin, GPIO.HIGH if q in active else GPIO.LOW)

        # Read current sensor for 5 seconds
        t_end = time.time() + 5
        while time.time() < t_end:
            cur = read_current()
            print(f"Current: {cur}")
            time.sleep(1)

    print("\n--- All lamps ON. Waiting 5 seconds... ---\n")
    time.sleep(5)

    print("Turning ALL lamps OFF.")
    all_off()
    GPIO.cleanup()
    print("Done.\n")


if __name__ == "__main__":
    main()
