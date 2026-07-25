#!/usr/bin/env python3
"""
methane_sensor.py

Minimal Axetris LGD reader, refactored from the standalone script into a
simple importable module.

Public API:

    init_methane(port=None, baud=9600)
        - Open serial port, auto-detect if port is None.
        - Start measurement stream if needed (sends CMD_START_MEAS).

    read_methane()
        - Read one measurement packet.
        - Returns a dict:
              {
                  "gas1": <float or None>,
                  "gas2": <float or None>,
                  "temperature_C": <float or None>,
                  "error_code": <int>,
              }
        - On error, raises RuntimeError.

    close_methane()
        - Close the serial port (optional, e.g., on shutdown).

No classes, no CLI, just functions and a global serial handle.
"""

import glob
import struct
import time

import serial  # pip install pyserial

# ----------------------------------------------------------------------
# Constants copied from original script
# ----------------------------------------------------------------------

START = 0x7B  # '{'
END   = 0x7D  # '}'

# Prebuilt 8-byte commands from the manual (little-endian size includes braces)
CMD_VERSION    = bytes([0x7B, ord('V'), 0x08, 0x00, 0x00, 0x00, 0x27, 0x7D])
CMD_IDLE       = bytes([0x7B, ord('I'), 0x08, 0x00, 0x00, 0xEA, 0x4A, 0x7D])
CMD_START_MEAS = bytes([0x7B, ord('M'), 0x08, 0x00, 0x01, 0xEA, 0x45, 0x7D])

DEFAULT_BAUD = 9600
DEFAULT_TIMEOUT = 1.0

# ----------------------------------------------------------------------
# Module-level state
# ----------------------------------------------------------------------

_ser = None
_initialized = False

# ----------------------------------------------------------------------
# Helper functions (mostly lifted from your script)
# ----------------------------------------------------------------------

def _find_serial_port(explicit_port=None):
    if explicit_port:
        return explicit_port
    candidates = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if not candidates:
        raise RuntimeError("No serial ports found for methane sensor.")
    # Heuristic: prefer the lowest-numbered device
    return candidates[0]


def _open_serial(port, baud):
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=DEFAULT_TIMEOUT,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    return ser


def _read_exact(ser, n):
    """Read exactly n bytes or raise TimeoutError."""
    data = bytearray()
    deadline = time.monotonic() + ser.timeout if ser.timeout else None
    while len(data) < n:
        chunk = ser.read(n - len(data))
        if chunk:
            data += chunk
        else:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"Timeout reading {n} bytes (got {len(data)}).")
    return bytes(data)


def _compute_sum8(buf):
    """Sum of bytes modulo 256."""
    return sum(buf) & 0xFF


def _read_packet(ser):
    """
    Read one framed packet { ID sizeLSB sizeMSB ... checksum }.
    Returns bytes including both braces. Validates checksum & end marker.
    """
    # Seek start byte
    while True:
        b = ser.read(1)
        if not b:
            raise TimeoutError("Timeout waiting for start byte '{'.")
        if b[0] == START:
            break
        # else keep discarding until we find '{'

    header = _read_exact(ser, 3)  # ID + size LSB + size MSB
    pid = header[0]
    size = header[1] | (header[2] << 8)

    if size < 6:
        # Minimum is {, ID, sizeLSB, sizeMSB, checksum, }
        raise ValueError(f"Invalid size {size}")

    # We've read 1 (start) + 3 (header) = 4 bytes so far.
    rest = _read_exact(ser, size - 4)  # includes checksum and final '}'
    if rest[-1] != END:
        raise ValueError("Packet missing closing '}'")

    packet = bytes([START]) + header + rest
    # Verify checksum: sum of all bytes except the final '}' must be 0 mod 256
    if _compute_sum8(packet[:-1]) != 0:
        raise ValueError("Checksum failed")

    return packet


def _parse_measurement(packet):
    """
    Return dict with error_code, optional gas1, gas2, temperature.
    Handles 16-byte (1 gas) and 24-byte (2 gases + temp) formats.
    """
    if packet[1] != ord('M'):
        raise ValueError("Not a measurement packet")
    size = packet[2] | (packet[3] << 8)
    body = packet[4:-2]  # status/code + payload + (padding)
    if len(body) < 2:
        raise ValueError("Measurement packet too short")

    # Bytes 5-6 of full packet are error status code (2 bytes little-endian)
    err_code = struct.unpack_from("<H", body, 0)[0]
    # Remaining bytes contain floats and padding to multiple of 8
    payload = body[2:]

    result = {"error_code": err_code, "gas1": None, "gas2": None, "temperature_C": None}

    if size == 16 and len(payload) >= 4:
        (g1,) = struct.unpack_from("<f", payload, 0)
        result["gas1"] = g1
    elif size == 24 and len(payload) >= 12:
        g1, g2, temp = struct.unpack_from("<fff", payload, 0)
        result["gas1"] = g1
        result["gas2"] = g2
        result["temperature_C"] = temp
    else:
        # Unknown/extended format; best effort: up to 3 floats
        floats = []
        for off in range(0, min(len(payload), 12), 4):
            if off + 4 <= len(payload):
                floats.append(struct.unpack_from("<f", payload, off)[0])
        for i, val in enumerate(floats, 1):
            result[f"f{i}"] = val

    return result


def _send_cmd(ser, cmd_bytes):
    """Send an 8-byte command."""
    ser.write(cmd_bytes)
    ser.flush()


def _maybe_start_measurements(ser):
    """
    On power-up the device typically begins sending a Version packet once,
    then continuous Measurement packets ~1 Hz. If nothing arrives, try to start.

    We do a best-effort:
      - Try to read one packet, ignore if it's version/etc.
      - If nothing / timeout, send CMD_START_MEAS and move on.
    """
    try:
        pkt = _read_packet(ser)
        pid = pkt[1]
        # If we got a measurement, good; if version/other, just ignore.
        if pid == ord('M'):
            # We drop it on the floor; the next read_methane() will get the next packet.
            return
        # otherwise ignore diagnostic packets etc.
    except TimeoutError:
        pass

    # If we didn't get anything useful, try sending START_MEAS
    try:
        _send_cmd(ser, CMD_START_MEAS)
    except serial.SerialException:
        pass


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def init_methane(port=None, baud=DEFAULT_BAUD):
    """
    Initialize the methane sensor:

      - Open the serial port (auto-detect if port is None).
      - Set up globals.
      - Try to start measurement stream if not already streaming.

    Safe to call multiple times; it will only open once.
    """
    global _ser, _initialized

    if _ser is not None and _ser.is_open:
        return  # already open

    ser_port = _find_serial_port(port)
    _ser = _open_serial(ser_port, baud)
    _maybe_start_measurements(_ser)
    _initialized = True


def read_methane():
    """
    Read a single measurement from the methane sensor.

    Returns a dict:
        {
            "gas1": <float or None>,
            "gas2": <float or None>,
            "temperature_C": <float or None>,
            "error_code": <int>,
        }

    If the device can't be read, raises RuntimeError.
    """
    global _ser, _initialized

    if _ser is None or not _ser.is_open:
        # Try to auto-init with defaults
        init_methane()

    try:
        pkt = _read_packet(_ser)
        meas = _parse_measurement(pkt)
        return meas
    except TimeoutError as te:
        raise RuntimeError(f"Methane sensor timeout: {te}") from te
    except Exception as e:
        raise RuntimeError(f"Methane sensor read error: {e}") from e


def close_methane():
    """Close the serial port, if open."""
    global _ser, _initialized
    if _ser is not None:
        try:
            _ser.close()
        except Exception:
            pass
    _ser = None
    _initialized = False


# Optional: simple sanity check if run directly
if __name__ == "__main__":
    print("[methane_sensor] Testing one read...")
    init_methane()
    try:
        m = read_methane()
        print("Measurement:", m)
    finally:
        close_methane()
