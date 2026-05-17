#!/bin/bash
# Master Initialization Script for OpenGNARBOX
# Runs once on first boot after firmware flash.

set -e

# Log all output for debugging
exec > /var/log/opengnarbox-init.log 2>&1

echo "Starting OpenGNARBOX Initialization Sequence..."
/usr/bin/oled-echo -b -- "OpenGNARBOX" "Initializing"
sleep 1
cd /mnt/secure/openfirmware

if [ -x ./postflash.sh ]; then
    ./postflash.sh
else
    bash ./postflash.sh
fi
sleep 1
if [ -x ./load.sh ]; then
    ./load.sh
else
    bash ./load.sh
fi

echo "[*] Disabling initialization service so it only runs once..."
systemctl disable opengnarbox-init.service || true
rm -f /etc/systemd/system/opengnarbox-init.service
systemctl daemon-reload || true

echo "[*] Initialization complete! Rebooting..."
/usr/bin/oled-echo -b -- "OpenGNARBOX" "READY!" "Rebooting..."
sleep 2

# Flush disk buffers to ensure all changes are written
sync
sleep 2

# Trigger a hardware cold reboot via MCU
echo 1 > /sys/bus/i2c/devices/i2c-GBX0001:00/system_state/cold_reboot

# Fallback reboot if MCU reboot fails
reboot
