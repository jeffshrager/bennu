#!/bin/bash
# Read the wind speed sensor from that A/D channel 1.
bytes=(`i2ctransfer -y 1 w1@0x6c 0x88 r3@0x6c | sed 's/0x//g' | tr a-f A-F`)
while [ $((0x${bytes[2]}&0x80)) != 0 ]; do
        bytes=(`i2ctransfer -y 1 r3@0x6c | sed 's/0x//g' | tr a-f A-F`)
done

voltage=`echo "scale=6; $((0x${bytes[0]}${bytes[1]}))*.0000625" | bc`
echo $voltage Volts '(Wind Sensor)'
