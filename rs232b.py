import serial
import struct
import threading
import os
from datetime import datetime
from collections import deque

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import Slider, TextBox

# ---------------------------------------------------------------------------
# Starting defaults (adjust here or via the on-screen controls at runtime)
# ---------------------------------------------------------------------------
DEFAULT_YMIN   = 0.0
DEFAULT_YMAX   = 100.0
DEFAULT_WINDOW = 100      # samples shown on the plot
DEFAULT_AVG    = 20       # rolling-average width in samples

PORT = '/dev/cu.usbserial-BG011WD7'
BAUD = 9600

# ---------------------------------------------------------------------------
# Log file
# ---------------------------------------------------------------------------
os.makedirs('results', exist_ok=True)
log_path = os.path.join('results', datetime.now().strftime('%Y%m%d_%H%M%S') + '.tsv')
log_file = open(log_path, 'w', buffering=1)   # line-buffered
log_file.write('timestamp\tvalue\n')
print(f'Logging to {log_path}')

# ---------------------------------------------------------------------------
# Shared data
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_vals = deque()

def _serial_reader():
    ser = serial.Serial(port=PORT, baudrate=BAUD, timeout=0.1)
    buf = b''
    while True:
        buf += ser.read(128)
        while True:
            start = buf.find(b'{')
            if start == -1:
                buf = b''
                break
            end = buf.find(b'}', start)
            if end == -1:
                buf = buf[start:]
                break
            packet = buf[start:end+1]
            buf = buf[end+1:]
            if len(packet) >= 14 and packet[1:2] == b'M':
                value = struct.unpack('<f', packet[6:10])[0]
                ts = datetime.now()
                with _lock:
                    _vals.append(value)
                log_file.write(f'{ts.isoformat()}\t{value}\n')
                print(f'{ts.isoformat()}  {value:.6g}')

threading.Thread(target=_serial_reader, daemon=True).start()

# ---------------------------------------------------------------------------
# Figure layout
#   Top 60 %  — data plot
#   Bottom 40% — controls
# ---------------------------------------------------------------------------
fig = plt.figure(figsize=(11, 6))

ax = fig.add_axes([0.08, 0.38, 0.88, 0.57])   # main plot
ax.set_xlabel('Sample (newest on right)')
ax.set_ylabel('Value')
ax.grid(True, alpha=0.3)
ax.set_ylim(DEFAULT_YMIN, DEFAULT_YMAX)

(line_raw,) = ax.plot([], [], color='steelblue', lw=1,  label='raw data')
(line_avg,) = ax.plot([], [], color='tomato',    lw=2,  label='running avg')
ax.legend(loc='upper left', fontsize=8)

# -- Sliders --
ax_win = fig.add_axes([0.18, 0.24, 0.68, 0.04])
ax_avg = fig.add_axes([0.18, 0.16, 0.68, 0.04])

sl_window = Slider(ax_win, 'Window', 10, 500, valinit=DEFAULT_WINDOW, valstep=1, color='steelblue')
sl_avg    = Slider(ax_avg, 'Avg',     1, 200, valinit=DEFAULT_AVG,    valstep=1, color='tomato')

# -- Text boxes for Y limits --
fig.text(0.08, 0.07, 'Y min', ha='center', va='center', fontsize=9)
fig.text(0.08, 0.02, 'Y max', ha='center', va='center', fontsize=9)

ax_ymin = fig.add_axes([0.12, 0.045, 0.12, 0.04])
ax_ymax = fig.add_axes([0.12, 0.005, 0.12, 0.04])

tb_ymin = TextBox(ax_ymin, '', initial=str(DEFAULT_YMIN))
tb_ymax = TextBox(ax_ymax, '', initial=str(DEFAULT_YMAX))

fig.text(0.27, 0.045, '← type a value and press Enter', fontsize=8,
         va='center', color='gray')

time_text = fig.text(0.88, 0.025, '', fontsize=10, ha='right', va='center',
                     family='monospace', color='dimgray')

# ---------------------------------------------------------------------------
# Control state (plain mutable container so callbacks can write to it)
# ---------------------------------------------------------------------------
cfg = {
    'ymin':   DEFAULT_YMIN,
    'ymax':   DEFAULT_YMAX,
    'window': DEFAULT_WINDOW,
    'avg':    DEFAULT_AVG,
}

def _on_ymin(text):
    try:
        cfg['ymin'] = float(text)
        ax.set_ylim(cfg['ymin'], cfg['ymax'])
    except ValueError:
        pass

def _on_ymax(text):
    try:
        cfg['ymax'] = float(text)
        ax.set_ylim(cfg['ymin'], cfg['ymax'])
    except ValueError:
        pass

def _on_window(val):
    cfg['window'] = int(val)

def _on_avg(val):
    cfg['avg'] = int(val)

tb_ymin.on_submit(_on_ymin)
tb_ymax.on_submit(_on_ymax)
sl_window.on_changed(_on_window)
sl_avg.on_changed(_on_avg)

# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------
def _animate(_frame):
    with _lock:
        vals = list(_vals)

    if not vals:
        return line_raw, line_avg

    window = vals[-cfg['window']:]
    n  = len(window)
    xs = np.arange(n)

    line_raw.set_data(xs, window)

    avg_w = cfg['avg']
    avg = np.array([
        float(np.mean(window[max(0, i - avg_w + 1): i + 1]))
        for i in range(n)
    ])
    line_avg.set_data(xs, avg)

    ax.set_xlim(0, max(n - 1, 1))
    time_text.set_text(datetime.now().strftime('%Y-%m-%d  %H:%M:%S'))
    ax.set_title(
        f'RS232 live  |  {n} pts shown  |  avg over {avg_w}  |  '
        f'Y=[{cfg["ymin"]}, {cfg["ymax"]}]',
        fontsize=9
    )
    return line_raw, line_avg

ani = animation.FuncAnimation(fig, _animate, interval=200,
                              blit=False, cache_frame_data=False)

plt.show()
log_file.close()
