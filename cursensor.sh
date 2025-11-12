#!/bin/bash
# Read the current sensor from A/D channel 0
bytes=(`i2ctransfer -y 1 w1@0x6c 0xa8 r3@0x6c | sed 's/0x//g' | tr a-f A-F`)
while [ $((0x${bytes[2]}&0x80)) != 0 ]; do
	bytes=(`i2ctransfer -y 1 r3@0x6c | sed 's/0x//g' | tr a-f A-F`)
done
voltage=`echo "scale=6; $((0x${bytes[0]}${bytes[1]}))*.0000625" | bc`
echo $voltage Volts '(Current Sensor)'
