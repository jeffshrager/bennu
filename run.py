#!/usr/bin/env python3

import os
import sys
import time
import signal
import logging
from logging.handlers import RotatingFileHandler

import RPi.GPIO as GPIO

from adc_sensors import read_windspeed, read_current

# ----------------------------------------------------------------------
# CONFIGURATION BLOCK (edit these as needed)
# ----------------------------------------------------------------------

# GPIO numbering mode: use BCM so numbers match the pin labels here.
GPIO.setmode(GPIO.BCM)

# Quad -> GPIO pin mapping (EDIT if wiring changes)
QUAD_GPIO_PINS = {
    "bowport":   16,
    "bowstar":   23,
    "sternport": 24,
    "sternstar": 25,
}

# How often to re-read lamp.config (seconds)
CONFIG_POLL_INTERVAL = 15.0

# Default sensor sampling interval (seconds) – overridden by samplerate in lamp.config
DEFAULT_SAMPLE_INTERVAL = 15.0

# Config file name (in run directory / current working dir)
CONFIG_FILE = "lamp.config"

# Log file (in run directory)
LOG_FILE = "lamp_controller.log"

# Name of methane module & function (ADJUST to match your actual module)

from methane_sensor import init_methane, read_methane


# ----------------------------------------------------------------------
# GLOBAL STATE
# ----------------------------------------------------------------------

lamp_state = {name: False for name in QUAD_GPIO_PINS.keys()}  # False = off, True = on
sample_interval = DEFAULT_SAMPLE_INTERVAL
shutdown_requested = False


# ----------------------------------------------------------------------
# LOGGING SETUP
# ----------------------------------------------------------------------

def setup_logging():
    """Set up logging to file and stdout (for systemd)."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # File handler (rotating)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=30)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Stdout handler (systemd will capture this)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)


# ----------------------------------------------------------------------
# GPIO SETUP / TEARDOWN
# ----------------------------------------------------------------------

def setup_gpio():
    """Initialize GPIO outputs for all quads."""
    for quad_name, pin in QUAD_GPIO_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    logging.info("GPIO initialized for quads: %s", ", ".join(sorted(QUAD_GPIO_PINS.keys())))


def cleanup_gpio():
    """Reset GPIO on shutdown."""
    try:
        GPIO.cleanup()
        logging.info("GPIO cleaned up.")
    except Exception as e:
        logging.error("Error during GPIO cleanup: %s", e)


# ----------------------------------------------------------------------
# SIGNAL HANDLING
# ----------------------------------------------------------------------

def handle_signal(signum, frame):
    global shutdown_requested
    logging.info("Received signal %s, requesting shutdown.", signum)
    shutdown_requested = True


# ----------------------------------------------------------------------
# CONFIG PARSING AND LAMP CONTROL
# ----------------------------------------------------------------------

def parse_samplerate(value_str, current_interval):
    """Parse samplerate value like '15s' or '10' into seconds."""
    v = value_str.strip().lower()
    if v.endswith("s"):
        v = v[:-1].strip()
    try:
        seconds = float(v)
        if seconds <= 0:
            raise ValueError("samplerate must be > 0 seconds")
        return seconds
    except ValueError as e:
        logging.error("Invalid samplerate '%s': %s (keeping %.1f s)",
                      value_str, e, current_interval)
        return current_interval


def load_config(current_sample_interval):
    """
    Read lamp.config and produce:
      - desired lamp_state dict (bools)
      - possibly-updated sample_interval
    Logs any format errors.
    """
    desired_state = lamp_state.copy()
    new_sample_interval = current_sample_interval

    if not os.path.exists(CONFIG_FILE):
        logging.error("Config file '%s' not found; keeping previous settings.", CONFIG_FILE)
        return desired_state, new_sample_interval

    try:
        with open(CONFIG_FILE, "r") as f:
            lines = f.readlines()
    except Exception as e:
        logging.error("Error reading config file '%s': %s", CONFIG_FILE, e)
        return desired_state, new_sample_interval

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            logging.error("Config error line %d: '%s' (no '=')", lineno, line)
            continue

        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "samplerate":
            old_interval = new_sample_interval
            new_sample_interval = parse_samplerate(value, new_sample_interval)
            if new_sample_interval != old_interval:
                logging.info("Samplerate changed from %.1f s to %.1f s via config.",
                             old_interval, new_sample_interval)
            continue

        if key not in QUAD_GPIO_PINS:
            logging.error("Config error line %d: unknown key '%s' (value '%s')",
                          lineno, key, value)
            continue

        v_lower = value.lower()
        if v_lower in ("on", "off"):
            desired_state[key] = (v_lower == "on")
        else:
            logging.error("Config error line %d: invalid value '%s' for '%s' (expected on/off)",
                          lineno, value, key)

    return desired_state, new_sample_interval


def apply_lamp_state(new_state):
    """
    Set GPIO outputs to match new_state.
    Logs only when something actually changes.
    """
    global lamp_state

    for quad, desired_on in new_state.items():
        if quad not in QUAD_GPIO_PINS:
            logging.error("Internal error: unknown quad '%s' in apply_lamp_state.", quad)
            continue

        current_on = lamp_state.get(quad, False)
        if desired_on == current_on:
            continue  # no change

        pin = QUAD_GPIO_PINS[quad]
        GPIO.output(pin, GPIO.HIGH if desired_on else GPIO.LOW)
        lamp_state[quad] = desired_on
        logging.info("Quad %s set to %s (GPIO %d)", quad, "ON" if desired_on else "OFF", pin)


# ----------------------------------------------------------------------
# SENSOR READ FUNCTIONS (STUBS / WRAPPERS)
# ----------------------------------------------------------------------

def read_methane_wrapper():
    """
    Simple wrapper to plug into the logging code.
    Returns gas1 (CH4) or None on error.
    """
    try:
        meas = read_methane()
        return meas.get("gas1")
    except Exception as e:
        logging.error("Error reading methane sensor: %s", e)
        return None

def log_sensor_readings():
    """Read all sensors once and log/print the results."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    methane = read_methane_wrapper()
    wind = read_windspeed()
    current = read_current()

    # Use 'NA' for missing values so logs remain parseable
    fields = {
        "time": ts,
        "methane": "NA" if methane is None else methane,
        "windspeed": "NA" if wind is None else wind,
        "current": "NA" if current is None else current,
    }

    # Simple human-readable log line; easy to grep or TSV-parse later
    logging.info(
        "Sensors: time=%(time)s methane=%(methane)s windspeed=%(windspeed)s current=%(current)s",
        fields,
    )


# ----------------------------------------------------------------------
# MAIN LOOP
# ----------------------------------------------------------------------

def main():
    global sample_interval

    setup_logging()
    logging.info("=== Lamp controller starting up ===")

    try:
        from methane_sensor import init_methane
        init_methane()
        logging.info("Methane sensor initialized.")
    except Exception as e:
        logging.error("Could not initialize methane sensor: %s", e)

    setup_gpio()

    # Hook signals for clean shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Initial config load and lamp set
    desired, sample_interval = load_config(sample_interval)
    apply_lamp_state(desired)
    logging.info("Initial lamp states: %s", lamp_state)
    logging.info("Initial sensor sample interval: %.1f s", sample_interval)

    next_config_time = time.time() + CONFIG_POLL_INTERVAL
    next_sample_time = time.time() + sample_interval

    try:
        while not shutdown_requested:
            now = time.time()

            # Periodic config reload
            if now >= next_config_time:
                desired, new_sample_interval = load_config(sample_interval)
                apply_lamp_state(desired)

                # If samplerate changed, adjust next_sample_time
                if new_sample_interval != sample_interval:
                    logging.info("Updating sample_interval from %.1f to %.1f seconds",
                                 sample_interval, new_sample_interval)
                    sample_interval = new_sample_interval
                    next_sample_time = now + sample_interval

                next_config_time = now + CONFIG_POLL_INTERVAL

            # Periodic sensor sampling
            if now >= next_sample_time:
                log_sensor_readings()
                next_sample_time = now + sample_interval

            # Sleep a little to avoid busy-waiting
            time.sleep(0.5)

    except Exception as e:
        logging.exception("Unexpected error in main loop: %s", e)
    finally:
        logging.info("Shutting down controller...")
        cleanup_gpio()
        logging.info("=== Lamp controller stopped ===")


if __name__ == "__main__":
    main()
