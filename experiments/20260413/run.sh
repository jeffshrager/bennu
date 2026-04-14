#!/bin/bash
BASE="/home/bennu/software/bennu"
CONFIG="$BASE/lamp.config"
ALLON="$BASE/lamp_all_on.config"
ALLOFF="$BASE/lamp_all_off.config"
BP="$BASE/lamp_bp.config"
BS="$BASE/lamp_bs.config"
SS="$BASE/lamp_ss.config"
SP="$BASE/lamp_sp.config"
SLEEPSECS=60 # 1 minute
LOGFILE="$BASE/lamp_controller.log"
echo "**************** Experiment 20260413 started ****************" >> "$LOGFILE"
while true; do
    echo "ALL OFF...waiting $SLEEPSECS seconds..."
    cp "$ALLOFF" "$CONFIG"
    sleep "$SLEEPSECS"
    echo "All ON...waiting $SLEEPSECS seconds..."
    cp "$ALLON" "$CONFIG"
    sleep "$SLEEPSECS"
done
# Never gets here in this particular experiment
echo "**************** Experiment 20260413 ended ****************" >> "$LOGFILE"
