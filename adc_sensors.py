#!/usr/bin/env python3
"""
adc_sensors.py
Simple wrapper for reading windspeed and current sensors from the ADC
attached via I2C at address 0x6c.

This Python translation reproduces the behavior of the original bash scripts:

    - For windspeed:  i2ctransfer -y 1 w1@0x6c 0x88 r3@0x6c
    - For current:    i2ctransfer -y 1 w1@0x6c 0xa8 r3@0x6c
    - Re-read until (bytes[2] & 0x80) == 0
    - Voltage = (raw 16-bit value) * 0.0000625

Returned values are floats in volts.
"""

"""
-------------------------------------------------------------------------------
NOTES ON IMPLEMENTING THESE ADC READS USING smbus2 OR periphery
-------------------------------------------------------------------------------

The current Python module calls the `i2ctransfer` binary to read the ADC at
I2C address 0x6C. This exactly mimics the bash code already tested on the Pi.

However, the same logic can be implemented cleanly using a pure-Python I2C 
library such as **smbus2** (most common) or **periphery** (lower-level, but
stable). The key is that the ADC requires a *write-then-read* transaction:

    For windspeed:
        Write  : [0x88]   (select channel 1)
        Read   : 3 bytes  (MSB, LSB, Status)

    For current:
        Write  : [0xA8]   (select channel 2)
        Read   : 3 bytes

The bash loop checks the READY bit in the returned status byte:
        
        while (status_byte & 0x80) != 0:
            read 3 bytes again

This means the ADC does *not* immediately provide valid MSB/LSB data after
channel selection; it must internally complete a conversion. Only when the
high bit (0x80) clears does the MSB/LSB contain the correct measurement.

A pure-Python version would look like this (example using smbus2):

    from smbus2 import SMBus, i2c_msg

    with SMBus(1) as bus:
        # 1. Select channel by writing 1 byte
        bus.write_byte(0x6C, 0x88)    # or 0xA8 for the current sensor

        # 2. Read 3 bytes
        read = i2c_msg.read(0x6C, 3)
        bus.i2c_rdwr(read)
        data = list(read)   # [MSB, LSB, Status]

        # 3. Busy-wait until ADC indicates data ready
        while data[2] & 0x80:
            read = i2c_msg.read(0x6C, 3)
            bus.i2c_rdwr(read)
            data = list(read)

        # 4. Combine MSB/LSB into a 16-bit integer ("big-endian")
        raw_value = (data[0] << 8) | data[1]

        # 5. Scale by the same LSB as the bash script:
        voltage = raw_value * 0.0000625

The **periphery** library would follow exactly the same sequence:

    from periphery import I2C

    i2c = I2C("/dev/i2c-1")

    # 1. Write channel select byte
    i2c.transfer(0x6C, [I2C.Message([0x88])])

    # 2. Read 3 bytes
    msgs = [I2C.Message([0]*3, read=True)]
    i2c.transfer(0x6C, msgs)
    data = msgs[0].data

    # 3. Repeat reads until ready bit clears
    while data[2] & 0x80:
        msgs = [I2C.Message([0]*3, read=True)]
        i2c.transfer(0x6C, msgs)
        data = msgs[0].data

    # 4. Convert to voltage as before
    raw_value = (data[0] << 8) | data[1]
    voltage = raw_value * 0.0000625

Both approaches completely avoid shelling out to `i2ctransfer`, and allow the
same low-level control from Python. The behavior is **identical** to the bash
code and this module's current implementation.

The only requirement to switch to smbus2/periphery is knowing that the ADC uses:
    - A 1-byte channel select command
    - A 3-byte read: MSB, LSB, STATUS
    - Bit 7 of STATUS = 1 → Data NOT ready
    - Bit 7 of STATUS = 0 → Data ready
    - LSB scale = 0.0000625 V per unit

If at some point you want a pure-Python version, these code fragments are a
direct drop-in replacement for the i2ctransfer calls used here.
-------------------------------------------------------------------------------
"""

import subprocess


I2C_BUS = "1"
I2C_ADDR = "0x6c"
ADC_LSB = 0.0000625    # Same as your bash: raw * .0000625


def _run_i2ctransfer(args):
    """
    Run i2ctransfer and return list of byte strings WITHOUT '0x'.
    Example returned list: ['12', 'AF', '00']
    """
    output = subprocess.check_output(args, text=True)
    # Output looks like: '0x12 0xAF 0x00\n'
    # Strip '0x', normalize to uppercase hex
    parts = output.strip().split()
    cleaned = [p.replace("0x", "").upper() for p in parts]
    return cleaned


def _read_adc(channel_cmd):
    """
    Perform the busy-wait read sequence used in both sensor scripts.

        channel_cmd = '0x88' for windspeed
        channel_cmd = '0xa8' for current

    Returns voltage as a float.
    """

    # Initial read: w1@0x6c <channel_cmd> r3@0x6c
    args = [
        "i2ctransfer", "-y", I2C_BUS,
        f"w1@{I2C_ADDR}", channel_cmd,
        f"r3@{I2C_ADDR}",
    ]
    bytes_hex = _run_i2ctransfer(args)

    # Busy-wait until MSB ready (bytes[2] & 0x80 == 0)
    # Subsequent reads omit the write:
    # i2ctransfer -y 1 r3@0x6c
    while int(bytes_hex[2], 16) & 0x80:
        bytes_hex = _run_i2ctransfer([
            "i2ctransfer", "-y", I2C_BUS,
            f"r3@{I2C_ADDR}",
        ])

    # Combine bytes[0] and bytes[1] into a 16-bit integer
    raw_val = int(bytes_hex[0] + bytes_hex[1], 16)

    # Apply scale factor
    voltage = raw_val * ADC_LSB
    return voltage


def read_windspeed():
    """Return windspeed sensor voltage as a float."""
    try:
        return _read_adc("0x88")
    except Exception as e:
        raise RuntimeError(f"Error reading windspeed sensor: {e}")


def read_current():
    """Return current sensor voltage as a float."""
    try:
        return _read_adc("0xa8")
    except Exception as e:
        raise RuntimeError(f"Error reading current sensor: {e}")
