import serial
import struct

ser = serial.Serial(
    port='/dev/cu.usbserial-BG011WD7',
    baudrate=9600,
    timeout=0.1
)

buffer = b''

while True:
    buffer += ser.read(128)

    while True:
        start = buffer.find(b'{')
        if start == -1:
            buffer = b''
            break

        end = buffer.find(b'}', start)
        if end == -1:
            buffer = buffer[start:]
            break

        packet = buffer[start:end+1]
        buffer = buffer[end+1:]

        # Only process measurement packets
        if len(packet) >= 14 and packet[1:2] == b'M':
            # extract float (bytes 6–9)
            value_bytes = packet[6:10]
            value = struct.unpack('<f', value_bytes)[0]

            print("Value:", value)
