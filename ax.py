#!/usr/bin/env python3


# pip install pyserial


# python axetris_lgd_reader.py           # auto-detect port, print readings
# python axetris_lgd_reader.py --port /dev/ttyUSB0 --csv lgd_log.csv
# python axetris_lgd_reader.py --baud 115200
# python axetris_lgd_reader.py --send-version   # just query & print firmware/serial




import argparse
import glob
import struct
import sys
import time
from datetime import datetime


import serial


START = 0x7B  # '{'
END   = 0x7D  # '}'


# Prebuilt 8-byte commands from the manual (little-endian size includes braces)
CMD_VERSION   = bytes([0x7B, ord('V'), 0x08, 0x00, 0x00, 0x00, 0x27, 0x7D])
CMD_IDLE      = bytes([0x7B, ord('I'), 0x08, 0x00, 0x00, 0xEA, 0x4A, 0x7D])
CMD_START_MEAS= bytes([0x7B, ord('M'), 0x08, 0x00, 0x01, 0xEA, 0x45, 0x7D])
# Example Ping user-data (requires Idle first). Not needed for basic streaming.
CMD_PING_USER = bytes([0x7B, ord('P'), 0x08, 0x00, 0x10, 0x00, 0x1D, 0x7D])


DEFAULT_BAUD = 9600  # per manual
DEFAULT_TIMEOUT = 1.0


def find_serial_port(explicit_port=None):
    if explicit_port:
        return explicit_port
    candidates = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if not candidates:
        raise RuntimeError("No serial ports found. Plug the device in or pass --port.")
    # Heuristic: prefer the lowest-numbered device
    return candidates[0]


def open_serial(port, baud):
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


def read_exact(ser, n):
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


def compute_sum8(buf):
    """Sum of bytes modulo 256."""
    return sum(buf) & 0xFF


def read_packet(ser):
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


    header = read_exact(ser, 3)  # ID + size LSB + size MSB
    pid = header[0]
    size = header[1] | (header[2] << 8)


    if size < 6:
        # Minimum is {, ID, sizeLSB, sizeMSB, checksum, }
        raise ValueError(f"Invalid size {size}")


    # We've read 1 (start) + 3 (header) = 4 bytes so far.
    rest = read_exact(ser, size - 4)  # includes checksum and final '}'
    if rest[-1] != END:
        raise ValueError("Packet missing closing '}'")


    packet = bytes([START]) + header + rest
    # Verify checksum: sum of all bytes except the final '}' must be 0 mod 256
    if compute_sum8(packet[:-1]) != 0:
        raise ValueError("Checksum failed")


    return packet


def parse_version(packet):
    """
    Version response format per manual (64-byte response).
    Extract firmware version (16B) and serial (32B) if present.
    """
    # packet: { 'V' size lo hi status1 status2 ... data ... cs }
    if packet[1] != ord('V'):
        return None
    size = packet[2] | (packet[3] << 8)
    body = packet[4:-2]  # exclude checksum and final '}', body starts at status
    # Manual shows fields by absolute byte positions inside the response.
    # Be defensive about length.
    firmware = serialno = None
    if len(body) >= 58:  # status(2) + 16 + 32 + 2 + 2 + 2 + 1 + 1 ...
        firmware = body[2:18].rstrip(b"\x00").decode(errors="ignore")
        serialno = body[18:50].rstrip(b"\x00").decode(errors="ignore")
    return {"size": size, "firmware": firmware, "serial": serialno}


def parse_measurement(packet):
    """
    Return dict with id='M', error_code, optional gas1, gas2, temperature.
    Handles 16-byte (1 gas) and 24-byte (2 gases + temp) formats.
    """
    if packet[1] != ord('M'):
        return None
    size = packet[2] | (packet[3] << 8)
    body = packet[4:-2]  # status/code + payload + (padding)
    if len(body) < 2:
        raise ValueError("Measurement packet too short")
    # Bytes 5-6 of full packet are error status code (2 bytes little-endian)
    err_code = struct.unpack_from("<H", body, 0)[0]
    # Remaining bytes contain floats and padding to multiple of 8
    payload = body[2:]
    # Decide by packet size
    result = {"error_code": err_code}
    if size == 16 and len(payload) >= 4:
        (g1,) = struct.unpack_from("<f", payload, 0)
        result["gas1"] = g1
    elif size == 24 and len(payload) >= 12:
        g1, g2, temp = struct.unpack_from("<fff", payload, 0)
        result["gas1"] = g1
        result["gas2"] = g2
        result["temperature_C"] = temp
    else:
        # Unknown/extended format; try best-effort: read up to three floats
        floats = []
        for off in range(0, min(len(payload), 12), 4):
            if off + 4 <= len(payload):
                floats.append(struct.unpack_from("<f", payload, off)[0])
        for i, val in enumerate(floats, 1):
            result[f"f{i}"] = val
    return result


def send_cmd(ser, cmd_bytes):
    """
    Send an 8-byte command. For very long commands (>64 bytes) the manual
    recommends 5 ms delays every 8 bytes — not needed here.
    """
    ser.write(cmd_bytes)
    ser.flush()


def maybe_start_measurements(ser, start_if_idle=True):
    """
    On power-up the device typically begins sending a Version packet once,
    then continuous Measurement packets ~1 Hz. If nothing arrives, try to start.
    """
    try:
        pkt = read_packet(ser)
        # If it's a version packet, just print it and continue reading.
        if pkt[1] == ord('V'):
            v = parse_version(pkt)
            if v:
                print(f"[info] Firmware: {v['firmware'] or '?'} | Serial: {v['serial'] or '?'}")
            # Next packets should be measurements; fall through.
        else:
            # Push back by handling in caller; here we just return the first packet.
            return pkt
    except TimeoutError:
        pass


    # If we didn't get anything useful yet, optionally send start.
    if start_if_idle:
        try:
            send_cmd(ser, CMD_START_MEAS)
            # The device will ACK with an 'M' packet (no data), then begin streaming.
        except serial.SerialException:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Axetris LGD-Compact reader (CH4/C2H6).")
    ap.add_argument("--port", help="Serial port (e.g., /dev/ttyUSB0). Auto-detect if omitted.")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default 9600).")
    ap.add_argument("--csv", help="Write readings to CSV file.")
    ap.add_argument("--send-version", action="store_true", help="Query and print version/serial, then exit.")
    args = ap.parse_args()


    port = find_serial_port(args.port)
    print(f"[info] Using port {port} @ {args.baud} bps")


    try:
        ser = open_serial(port, args.baud)
    except Exception as e:
        print(f"[error] Could not open port: {e}")
        sys.exit(1)


    try:
        if args.send_version:
            send_cmd(ser, CMD_VERSION)
            pkt = read_packet(ser)
            if pkt[1] != ord('V'):
                print("[warn] Unexpected response (not 'V').")
            v = parse_version(pkt)
            if v:
                print(f"Firmware: {v['firmware'] or '?'}")
                print(f"Serial:   {v['serial'] or '?'}")
            else:
                print(pkt)
            return


        # Try to get the stream going
        first_pkt = maybe_start_measurements(ser)


        # CSV setup
        csvfh = None
        if args.csv:
            csvfh = open(args.csv, "a", buffering=1)
            if csvfh.tell() == 0:
                csvfh.write("timestamp,gas1,gas2,temperature_C,error_code\n")


        # If we already have a packet, handle it before the loop
        if first_pkt:
            packets = [first_pkt]
        else:
            packets = []


        print("[info] Streaming measurements. Ctrl-C to stop.")
        while True:
            if packets:
                pkt = packets.pop(0)
            else:
                pkt = read_packet(ser)


            pid = pkt[1]
            if pid == ord('M'):
                meas = parse_measurement(pkt)
                ts = datetime.now().isoformat(timespec="seconds")
                g1 = meas.get("gas1")
                g2 = meas.get("gas2")
                tC = meas.get("temperature_C")
                err = meas.get("error_code", 0)


                # Pretty print line
                fields = [f"time={ts}"]
                if g1 is not None:
                    fields.append(f"gas1={g1:.3f}")
                if g2 is not None:
                    fields.append(f"gas2={g2:.3f}")
                if tC is not None:
                    fields.append(f"T={tC:.2f}°C")
                if err:
                    fields.append(f"err=0x{err:04X}")
                print("  ".join(fields))


                if csvfh:
                    csvfh.write(f"{ts},{g1 if g1 is not None else ''},{g2 if g2 is not None else ''},{tC if tC is not None else ''},{err}\n")


            elif pid in (ord('E'), ord('F')):
                label = 'ERROR' if pid == ord('E') else 'FAILURE'
                print(f"[{label}] packet received")
            elif pid in (ord('P'), ord('C'), ord('I'), ord('S'), ord('V'), ord('D')):
                # Acknowledge or diagnostic; show brief info
                print(f"[info] Packet '{chr(pid)}' size={pkt[2] | (pkt[3]<<8)}")
            else:
                print(f"[warn] Unknown packet ID 0x{pid:02X}")


    except KeyboardInterrupt:
        print("\n[info] Stopped by user.")
    except TimeoutError as te:
        print(f"[error] {te}")
    except Exception as e:
        print(f"[error] {e}")
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()