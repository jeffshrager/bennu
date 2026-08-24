#!/usr/bin/env python3


# pip install pyserial matplotlib


# GUI version of ax.py: live scrolling plot of Axetris readings.
#
# python axg.py                      # auto-detect port
# python axg.py --port /dev/ttyUSB0
# python axg.py --baud 115200
# python axg.py --test                # no serial port; drive the signal by hand


import argparse
import json
import os
import random
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


WINDOW = 300  # samples kept in the buffer (upper bound for history display)
DEFAULT_SMOOTH_WINDOW = 10  # running-mean window (samples) applied before plotting
MAX_SMOOTH_WINDOW = 50
DEFAULT_HISTORY = 100  # points shown on the plot at once

YAXIS_HALF_RANGE = 1.0  # Y axis always spans center +/- this
YAXIS_RECENTER_FRACTION = 0.8  # recenter once the value crosses this fraction of the half-range
YAXIS_INIT_CENTER = 2.0

TEST_SIGNAL_MIN = 0.0
TEST_SIGNAL_MAX = 6.0
TEST_SIGNAL_INIT = 2.0
TEST_FEED_INTERVAL = 0.2  # seconds between simulated samples in --test mode
TEST_NOISE_FRACTION = 0.05  # +/- 5% random noise applied to the TEST signal

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mobile_bennu_logo.png")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "axg.json")
CONFIG_DEFAULTS = {"smooth_window": DEFAULT_SMOOTH_WINDOW, "history": DEFAULT_HISTORY}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return {**CONFIG_DEFAULTS, **cfg}
    except (OSError, ValueError):
        save_config(CONFIG_DEFAULTS)
        return dict(CONFIG_DEFAULTS)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


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
def build_gui(config, initial_window=DEFAULT_SMOOTH_WINDOW, initial_history=DEFAULT_HISTORY,
              test_mode=False):
    fig = plt.figure(figsize=(10, 7.0))
    fig.canvas.manager.set_window_title("Axetris LGD - Live")

    try:
        logo_img = plt.imread(LOGO_PATH)
        logo_h, logo_w = logo_img.shape[0], logo_img.shape[1]
        logo_axes_w = 0.14 * 1.25 * 2
        logo_axes_h = logo_axes_w * (logo_h / logo_w) * (fig.get_figwidth() / fig.get_figheight())
        # Under the graph, centered on its right half (graph spans
        # x=[0.10, 0.95], so right half is [0.525, 0.95], centered on
        # x=0.7375). Anchored below the graph's bottom (y=0.40), nudged
        # down ~0.25in further, and allowed to extend down over the
        # (normally hidden) sliders at this larger size.
        graph_right_half_center_x = 0.525 + (0.95 - 0.525) / 2
        logo_top = 0.34 - 0.25 / fig.get_figheight()
        ax_logo = fig.add_axes(
            [graph_right_half_center_x - logo_axes_w / 2, logo_top - logo_axes_h,
             logo_axes_w, logo_axes_h]
        )
        ax_logo.imshow(logo_img)
        ax_logo.axis("off")
    except OSError as e:
        print(f"[warn] Could not load logo from {LOGO_PATH}: {e}")

    ax = fig.add_axes([0.10, 0.40, 0.85, 0.52])
    ax.set_ylabel("Concentration")
    yaxis_state = {"center": YAXIS_INIT_CENTER}
    ax.set_ylim(yaxis_state["center"] - YAXIS_HALF_RANGE, yaxis_state["center"] + YAXIS_HALF_RANGE)
    ax.grid(True, alpha=0.3)

    (line1,) = ax.plot([], [], color="steelblue", lw=1.5, label="gas1")
    (line2,) = ax.plot([], [], color="darkorange", lw=1.5, label="gas2")
    ax.legend(loc="upper left", fontsize=8)

    status_text = fig.text(0.10, 0.26, "", fontsize=9, family="monospace")

    smooth_state = {"window": initial_window}
    ax_smooth = fig.add_axes([0.32, 0.19, 0.53, 0.03])
    smooth_slider = Slider(
        ax_smooth, "smoothing (samples)", 1, MAX_SMOOTH_WINDOW,
        valinit=initial_window, valstep=1,
    )

    history_state = {"points": initial_history}
    ax_hist = fig.add_axes([0.32, 0.13, 0.53, 0.03])
    hist_slider = Slider(
        ax_hist, "history (points)", 5, WINDOW,
        valinit=initial_history, valstep=5,
    )

    def _on_smooth_change(val):
        smooth_state["window"] = int(val)
        config["smooth_window"] = int(val)
        save_config(config)

    def _on_hist_change(val):
        history_state["points"] = int(val)
        config["history"] = int(val)
        save_config(config)

    smooth_slider.on_changed(_on_smooth_change)
    hist_slider.on_changed(_on_hist_change)

    # Test mode: an always-visible slider (not gated by the hide/show toggle)
    # that lets you set the simulated gas1 signal by hand instead of reading
    # from a serial port. A background thread feeds its current value into
    # the shared buffers at a steady cadence so the rest of the pipeline
    # (smoothing, history window, Y-axis recentering) behaves as it would
    # with a real signal.
    test_slider = None
    if test_mode:
        ax_test = fig.add_axes([0.10, 0.19, 0.18, 0.03])
        test_slider = Slider(
            ax_test, "TEST signal", TEST_SIGNAL_MIN, TEST_SIGNAL_MAX,
            valinit=TEST_SIGNAL_INIT, valstep=0.01, color="tomato",
        )
        test_state = {"value": test_slider.val}
        test_slider.on_changed(lambda val: test_state.__setitem__("value", float(val)))

        def _test_feed():
            while not _stop.is_set():
                base = test_state["value"]
                noisy = base + random.uniform(-1.0, 1.0) * TEST_NOISE_FRACTION * base
                with _lock:
                    _times.append(datetime.now())
                    _gas1.append(noisy)
                    _gas2.append(float("nan"))
                _stop.wait(TEST_FEED_INTERVAL)

        threading.Thread(target=_test_feed, daemon=True).start()

    ax_reset = fig.add_axes([0.32, 0.05, 0.16, 0.05])
    reset_button = Button(ax_reset, "Reset defaults", color="whitesmoke", hovercolor="lightgray")

    def _on_reset_click(_event):
        save_config(dict(CONFIG_DEFAULTS))
        smooth_slider.set_val(CONFIG_DEFAULTS["smooth_window"])
        hist_slider.set_val(CONFIG_DEFAULTS["history"])

    reset_button.on_clicked(_on_reset_click)

    # Tiny, low-contrast toggle tucked in the lower-right corner. Clicking it
    # shows/hides the sliders and reset button. Faint fill + border + glyph
    # so it's findable on close inspection without standing out at a glance
    # (pure white on white, with no border, was invisible even when looked
    # for directly).
    controls_state = {"visible": False}
    ax_toggle = fig.add_axes([0.955, 0.010, 0.035, 0.025])
    toggle_button = Button(ax_toggle, "⋮", color="#f0f0f0", hovercolor="#c0c0c0")
    toggle_button.label.set_color("#b0b0b0")
    toggle_button.label.set_fontsize(9)
    for spine in ax_toggle.spines.values():
        spine.set_visible(True)
        spine.set_color("#d8d8d8")
        spine.set_linewidth(0.6)

    def _apply_controls_visibility():
        visible = controls_state["visible"]
        ax_smooth.set_visible(visible)
        ax_hist.set_visible(visible)
        ax_reset.set_visible(visible)
        fig.canvas.draw_idle()

    def _on_toggle_click(_event):
        controls_state["visible"] = not controls_state["visible"]
        _apply_controls_visibility()

    toggle_button.on_clicked(_on_toggle_click)
    _apply_controls_visibility()

    # Widgets must be kept alive by a strong reference for the life of the
    # figure, or matplotlib's callbacks silently stop firing once garbage
    # collected.
    fig._widgets = (smooth_slider, hist_slider, reset_button, toggle_button, test_slider)

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

            # Smooth over the full buffer, then window down to the last
            # `history` points for display, so early points in the visible
            # window still get smoothing context from before it.
            hist = history_state["points"]
            times_d = times[-hist:]
            g1_d = g1[-hist:]
            g2_d = g2[-hist:]

            t0 = times_d[0]
            xs = [(t - t0).total_seconds() for t in times_d]
            line1.set_data(xs, g1_d)
            line2.set_data(xs, g2_d)
            ax.set_xlim(0, max(xs[-1], 1))

            y_value = g1_d[-1]
            if y_value == y_value:  # not NaN
                center = yaxis_state["center"]
                if abs(y_value - center) >= YAXIS_HALF_RANGE * YAXIS_RECENTER_FRACTION:
                    center = round(y_value * 2) / 2
                    yaxis_state["center"] = center
                ax.set_ylim(center - YAXIS_HALF_RANGE, center + YAXIS_HALF_RANGE)

            latest = f"gas1={g1_d[-1]:.3f}"
            if g2_d[-1] == g2_d[-1]:  # not NaN
                latest += f"  gas2={g2_d[-1]:.3f}"

            if len(times) >= 2:
                span = (times[-1] - times[0]).total_seconds()
                rate = f"{(len(times) - 1) / span:.2f} Hz" if span > 0 else "n/a"
            else:
                rate = "n/a"

            status_text.set_text(
                f"{times_d[-1].strftime('%H:%M:%S')}  {latest}  "
                f"({len(times_d)}/{len(times)} pts, {rate})"
            )
        else:
            status_text.set_text("waiting for data...")

        return line1, line2

    ani = animation.FuncAnimation(fig, _animate, interval=250, cache_frame_data=False)
    return fig, ani


def main():
    ap = argparse.ArgumentParser(description="Axetris LGD-Compact reader with live GUI.")
    ap.add_argument("--port", help="Serial port (e.g., /dev/ttyUSB0). Auto-detect if omitted.")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default 9600).")
    ap.add_argument("--window", type=int, default=None,
                     help="initial running-mean smoothing window, in samples "
                          "(default: last saved value, or "
                          f"{DEFAULT_SMOOTH_WINDOW}); adjustable live via the slider")
    ap.add_argument("--history", type=int, default=None,
                     help="initial number of points shown on the plot "
                          f"(default: last saved value, or {DEFAULT_HISTORY}, max {WINDOW}); "
                          "adjustable live via the slider")
    ap.add_argument("--test", action="store_true",
                     help="Test mode: skip the serial port and expose an always-visible "
                          "slider to set the simulated signal value by hand.")
    args = ap.parse_args()

    if args.test:
        print("[info] Test mode: no serial port will be opened; use the TEST signal slider.")
    else:
        try:
            port = find_serial_port(args.port)
        except Exception as e:
            print(f"[error] {e}")
            sys.exit(1)
        print(f"[info] Using port {port} @ {args.baud} bps")

        reader = threading.Thread(target=_serial_reader, args=(port, args.baud), daemon=True)
        reader.start()

    config = load_config()
    initial_window = args.window if args.window is not None else config["smooth_window"]
    initial_history = args.history if args.history is not None else config["history"]

    fig, ani = build_gui(config, initial_window=initial_window, initial_history=initial_history,
                          test_mode=args.test)
    try:
        fig.canvas.manager.full_screen_toggle()
    except Exception as e:
        print(f"[warn] Could not switch to full screen: {e}")
    try:
        plt.show()
    finally:
        _stop.set()


if __name__ == "__main__":
    main()
