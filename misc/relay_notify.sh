#!/bin/bash
# start by: nohup ./relay_notify.sh > relay_notify.log 2>&1 &

TOPIC="rome-is-reachable"

while true; do
    if ssh -o BatchMode=yes -o ConnectTimeout=10 \
           -p 21965 localhost true >/dev/null 2>&1
    then
        curl -s -d "SSH tunnel is UP" "https://ntfy.sh/$TOPIC" >/dev/null
    else
        curl -s -d "SSH tunnel is DOWN" "https://ntfy.sh/$TOPIC" >/dev/null
    fi

    sleep 3600
done
