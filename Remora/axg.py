#!/usr/bin/env python3


# pip install pyserial matplotlib


# GUI version of ax.py: live scrolling plot of Axetris readings, plus a
# "Lamp" button (black = off, blue = on) that drives GPIO pin 5 (BCM)
# high for as long as the lamp is on.
#
# python axg.py                      # auto-detect port
# python axg.py --port /dev/ttyUSB0
# python axg.py --baud 115200


import argparse
import sys
import threading
from collections import deque
from datetime import datetime

import matplotlib.animation as animation
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider

from ax import (
    DEFAULT_BAUD,
    find_serial_port,
    maybe_start_measurements,
    open_serial,
    parse_measurement,
    read_packet,
)


LAMP_PIN = 5  # BCM numbering
WINDOW = 300  # samples kept/shown on the plot
DEFAULT_SMOOTH_WINDOW = 10  # running-mean window (samples) applied before plotting
MAX_SMOOTH_WINDOW = 50


try:
    import RPi.GPIO as GPIO
    HAVE_GPIO = True
except ImportError:
    GPIO = None
    HAVE_GPIO = False


def rolling_mean(values, window):
    """Trailing running mean over the last `window` non-NaN samples."""
    if window <= 1:
        return list(values)
    out = []
    buf = deque(maxlen=window)
    for v in values:
        if v == v:  # skip NaN
            buf.append(v)
        out.append(sum(buf) / len(buf) if buf else float("nan"))
    return out


def setup_lamp_gpio():
    if not HAVE_GPIO:
        print("[warn] RPi.GPIO not available; Lamp button will only update the UI.")
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LAMP_PIN, GPIO.OUT, initial=GPIO.LOW)


def set_lamp(on):
    if HAVE_GPIO:
        GPIO.output(LAMP_PIN, GPIO.HIGH if on else GPIO.LOW)


def cleanup_lamp_gpio():
    if HAVE_GPIO:
        GPIO.output(LAMP_PIN, GPIO.LOW)
        GPIO.cleanup(LAMP_PIN)


# ---------------------------------------------------------------------------
# Background serial reader -> shared ring buffers
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_times = deque(maxlen=WINDOW)
_gas1 = deque(maxlen=WINDOW)
_gas2 = deque(maxlen=WINDOW)
_stop = threading.Event()
_reader_error = [None]


def _serial_reader(port, baud):
    try:
        ser = open_serial(port, baud)
    except Exception as e:
        _reader_error[0] = f"Could not open port {port}: {e}"
        return

    try:
        pending = []
        first_pkt = maybe_start_measurements(ser)
        if first_pkt:
            pending.append(first_pkt)

        while not _stop.is_set():
            if pending:
                pkt = pending.pop(0)
            else:
                try:
                    pkt = read_packet(ser)
                except TimeoutError:
                    continue

            if pkt[1] != ord('M'):
                continue
            meas = parse_measurement(pkt)
            g1 = meas.get("gas1") if meas else None
            if g1 is None:
                continue
            g2 = meas.get("gas2")

            with _lock:
                _times.append(datetime.now())
                _gas1.append(g1)
                _gas2.append(g2 if g2 is not None else float("nan"))
    except Exception as e:
        _reader_error[0] = str(e)
    finally:
        try:
            ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
def build_gui(initial_window=DEFAULT_SMOOTH_WINDOW):
    fig = plt.figure(figsize=(10, 6.6))
    fig.canvas.manager.set_window_title("Axetris LGD - Live")

    ax = fig.add_axes([0.10, 0.34, 0.85, 0.58])
    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Concentration")
    ax.grid(True, alpha=0.3)

    (line1,) = ax.plot([], [], color="steelblue", lw=1.5, label="gas1")
    (line2,) = ax.plot([], [], color="darkorange", lw=1.5, label="gas2")
    ax.legend(loc="upper left", fontsize=8)

    status_text = fig.text(0.10, 0.20, "", fontsize=9, family="monospace")

    smooth_state = {"window": initial_window}
    ax_smooth = fig.add_axes([0.15, 0.13, 0.70, 0.03])
    smooth_slider = Slider(
        ax_smooth, "smoothing (samples)", 1, MAX_SMOOTH_WINDOW,
        valinit=initial_window, valstep=1,
    )
    smooth_slider.on_changed(lambda val: smooth_state.__setitem__("window", int(val)))
    fig._smooth_slider = smooth_slider  # keep a reference alive

    lamp_state = {"on": False}
    ax_lamp = fig.add_axes([0.40, 0.03, 0.20, 0.09])
    lamp_button = Button(ax_lamp, "Lamp", color="black", hovercolor="dimgray")
    lamp_button.label.set_color("white")
    lamp_button.label.set_fontweight("bold")

    def _paint_lamp():
        if lamp_state["on"]:
            lamp_button.color, lamp_button.hovercolor = "blue", "royalblue"
        else:
            lamp_button.color, lamp_button.hovercolor = "black", "dimgray"
        lamp_button.ax.set_facecolor(lamp_button.color)
        fig.canvas.draw_idle()

    def _on_lamp_click(_event):
        lamp_state["on"] = not lamp_state["on"]
        set_lamp(lamp_state["on"])
        _paint_lamp()

    lamp_button.on_clicked(_on_lamp_click)
    _paint_lamp()

    def _animate(_frame):
        with _lock:
            times = list(_times)
            g1 = list(_gas1)
            g2 = list(_gas2)

        if _reader_error[0]:
            status_text.set_text(f"[error] {_reader_error[0]}")
        elif times:
            window = smooth_state["window"]
            g1 = rolling_mean(g1, window)
            g2 = rolling_mean(g2, window)

            t0 = times[0]
            xs = [(t - t0).total_seconds() for t in times]
            line1.set_data(xs, g1)
            line2.set_data(xs, g2)
            ax.set_xlim(0, max(xs[-1], 1))

            finite = [v for v in g1 + g2 if v == v]  # drop NaN
            if finite:
                lo, hi = min(finite), max(finite)
                pad = max((hi - lo) * 0.1, 0.01)
                ax.set_ylim(lo - pad, hi + pad)

            latest = f"gas1={g1[-1]:.3f}"
            if g2[-1] == g2[-1]:  # not NaN
                latest += f"  gas2={g2[-1]:.3f}"
            status_text.set_text(
                f"{times[-1].strftime('%H:%M:%S')}  {latest}  ({len(times)} pts)"
            )
        else:
            status_text.set_text("waiting for data...")

        return line1, line2

    ani = animation.FuncAnimation(fig, _animate, interval=250, cache_frame_data=False)
    return fig, ani


def main():
    ap = argparse.ArgumentParser(description="Axetris LGD-Compact reader with live GUI + lamp control.")
    ap.add_argument("--port", help="Serial port (e.g., /dev/ttyUSB0). Auto-detect if omitted.")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default 9600).")
    ap.add_argument("--window", type=int, default=DEFAULT_SMOOTH_WINDOW,
                     help=f"initial running-mean smoothing window, in samples "
                          f"(default {DEFAULT_SMOOTH_WINDOW}); adjustable live via the slider")
    args = ap.parse_args()

    try:
        port = find_serial_port(args.port)
    except Exception as e:
        print(f"[error] {e}")
        sys.exit(1)
    print(f"[info] Using port {port} @ {args.baud} bps")

    setup_lamp_gpio()

    reader = threading.Thread(target=_serial_reader, args=(port, args.baud), daemon=True)
    reader.start()

    fig, ani = build_gui(initial_window=args.window)
    try:
        plt.show()
    finally:
        _stop.set()
        set_lamp(False)
        cleanup_lamp_gpio()


if __name__ == "__main__":
    main()
