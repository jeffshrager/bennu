#!/bin/bash
BASE="/home/bennu/software/bennu"
CONFIG="$BASE/lamp.config"
ALLON="$BASE/lamp_all_on.config"
ALLOFF="$BASE/lamp_all_off.config"
SLEEPSECS=300  # 5 minutes
LOGFILE="$BASE/lamp_controller.log"
echo "**************** Experiment 20251209a started ****************" >> "$LOGFILE"
while true; do
    echo "ALL ON...waiting $SLEEPSECS seconds..."
    cp "$ALLON" "$CONFIG"
    sleep "$SLEEPSECS"
    echo "ALL OFF...waiting $SLEEPSECS seconds..."
    cp "$ALLOFF" "$CONFIG"
    sleep "$SLEEPSECS"
done
# Never gets here in this particular experiment
echo "**************** Experiment 20251209a ended ****************" >> "$LOGFILE"
