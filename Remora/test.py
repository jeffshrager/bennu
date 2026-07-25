#!/usr/bin/env python3
import time
import itertools
import sys
import RPi.GPIO as GPIO

from adc_sensors import read_windspeed, read_current
from methane_sensor import init_methane, read_methane

# ----------------------------------------------------------------------
# GPIO CONFIG – EDIT TO MATCH YOUR MAIN CONTROLLER
# ----------------------------------------------------------------------

QUAD_GPIO_PINS = {
    "bowport":   24,
    "bowstar":   25,
    "sternport": 16,
    "sternstar": 23,
}

QUADS = list(QUAD_GPIO_PINS.keys())


# ----------------------------------------------------------------------
# GPIO SETUP
# ----------------------------------------------------------------------

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for pin in QUAD_GPIO_PINS.values():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

def all_off():
    for pin in QUAD_GPIO_PINS.values():
        GPIO.output(pin, GPIO.LOW)

def set_lamps(quads):
    """quads: iterable of quad names to turn ON; all others turn OFF"""
    for q, pin in QUAD_GPIO_PINS.items():
        GPIO.output(pin, GPIO.HIGH if q in quads else GPIO.LOW)


# ----------------------------------------------------------------------
# LAMP TESTS
# ----------------------------------------------------------------------

def test_single_quads():
    print("\n=========================")
    print("TESTING SINGLE QUADS")
    print("=========================\n")

    for quad in QUADS:
        print(f"\n>>> Testing {quad}: ON for 5 seconds...")
        set_lamps([quad])
        time.sleep(5)

        print(f"Turning {quad} OFF.")
        set_lamps([])

        input(f"Did {quad} behave correctly? Press ENTER to continue...")

    print("\nSingle-quad tests complete.\n")


def test_combinations():
    print("\n=========================")
    print("TESTING LAMP COMBINATIONS")
    print("=========================\n")

    # All subsets of size 2, 3, and 4
    combos = []
    for r in [2, 3, 4]:
        combos.extend(itertools.combinations(QUADS, r))

    for combo in combos:
        combo = list(combo)
        print(f"\n>>> Testing combination: {combo}")
        print("Turning ON. Current sensor should respond.")

        set_lamps(combo)
        print("Reading current sensor at 1 Hz. Press ENTER to stop this combo.")
        print("(Leave ENTER unpressed to watch current draw for a while.)")

        # Stream until ENTER
        while True:
            if sys.stdin in select_for_stdin():
                _ = sys.stdin.readline()
                break
            cur = read_current()
            print(f"Current sensor: {cur}")
            time.sleep(1)

        print("Turning all lamps OFF...\n")
        all_off()

    print("\nAll combination tests complete.\n")


# ----------------------------------------------------------------------
# SENSOR STREAMING HELPERS
# ----------------------------------------------------------------------

def select_for_stdin():
    """Cross-platform-ish hack using select (works on Linux/Unix)."""
    import select
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    return readable


# ----------------------------------------------------------------------
# SENSOR TESTS
# ----------------------------------------------------------------------

def test_windspeed():
    print("\n=========================")
    print("TESTING WINDSPEED SENSOR")
    print("=========================\n")

    print("Streaming windspeed once per second.")
    print("Press ENTER to stop.")

    while True:
        if sys.stdin in select_for_stdin():
            _ = sys.stdin.readline()
            break
        w = read_windspeed()
        print(f"Windspeed: {w}")
        time.sleep(1)

    print("Windspeed test complete.\n")


def test_methane():
    print("\n=========================")
    print("TESTING METHANE SENSOR")
    print("=========================\n")

    init_methane()

    print("Streaming methane readings (ppm).")
    print("Press ENTER to stop.")

    while True:
        if sys.stdin in select_for_stdin():
            _ = sys.stdin.readline()
            break

        try:
            meas = read_methane()
            ppm = meas.get("gas1")
            print(f"Methane (gas1): {ppm}")
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(1)

    print("Methane sensor test complete.\n")


# ----------------------------------------------------------------------
# MAIN MENU
# ----------------------------------------------------------------------

def main():
    print("\n====================================")
    print(" RASPBERRY PI LAMP + SENSOR TESTING ")
    print("====================================\n")

    setup_gpio()
    all_off()

    while True:
        print("\nSelect a test:")
        print(" 1) Test single lamp quads")
        print(" 2) Test lamp combinations + current sensor")
        print(" 3) Test windspeed sensor")
        print(" 4) Test methane sensor")
        print(" 5) ALL tests (full suite)")
        print(" 0) EXIT")
        choice = input("> ").strip()

        if choice == "1":
            test_single_quads()
        elif choice == "2":
            test_combinations()
        elif choice == "3":
            test_windspeed()
        elif choice == "4":
            test_methane()
        elif choice == "5":
            test_single_quads()
            test_combinations()
            test_windspeed()
            test_methane()
        elif choice == "0":
            print("Exiting. Turning all lamps OFF.")
            all_off()
            GPIO.cleanup()
            return
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    try:
        main()
    finally:
        all_off()
        GPIO.cleanup()
