#!/bin/bash
set -e

# ---------------------------------------------------------------------
# 1. Where are we?
# ---------------------------------------------------------------------
WD="$(pwd)"
echo "Installing bennu into: $WD"

# ---------------------------------------------------------------------
# 2. Clone repo into the current directory
# ---------------------------------------------------------------------
if [ -d "$WD/bennu" ]; then
    echo "Directory 'bennu' already exists. Remove it or run elsewhere."
    exit 1
fi

git clone https://github.com/jeffshrager/bennu.git
echo "Repo cloned."

# ---------------------------------------------------------------------
# 3. Prepare systemd service
# ---------------------------------------------------------------------
SERVICE_SRC="$WD/bennu/lamp-controller.service"
SERVICE_DST="/etc/systemd/system/lamp-controller.service"

if [ ! -f "$SERVICE_SRC" ]; then
    echo "ERROR: Cannot find lamp-controller.service in cloned repo."
    exit 1
fi

echo "Configuring systemd service with working directory: $WD/bennu"

# Use the real absolute path, even if the script was run from a symlink
REALDIR="$(realpath "$WD/bennu")"

# Create a temp copy for editing
TMPFILE=$(mktemp)

# ---------------------------------------------------------------------
# 4. Rewrite WorkingDirectory= and ExecStart=
# ---------------------------------------------------------------------
sed \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=${REALDIR}|" \
    -e "s|^ExecStart=.*|ExecStart=/usr/bin/python3 ${REALDIR}/run.py|" \
    "$SERVICE_SRC" > "$TMPFILE"

# ---------------------------------------------------------------------
# 5. Install service
# ---------------------------------------------------------------------
sudo mv "$TMPFILE" "$SERVICE_DST"
sudo chmod 644 "$SERVICE_DST"
sudo systemctl daemon-reload

# ---------------------------------------------------------------------
# 6. Enable + start service
# ---------------------------------------------------------------------
sudo systemctl enable lamp-controller.service
sudo systemctl restart lamp-controller.service

echo "Installation complete."
echo "Check logs with:"
echo "  journalctl -u lamp-controller.service -f"
