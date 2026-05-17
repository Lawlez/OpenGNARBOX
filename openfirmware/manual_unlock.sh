#!/bin/bash
# OpenGNARBOX Offline SSH Fallback

if [ -z "$1" ]; then
    echo "Usage: ./manual_unlock.sh <MASTER_LUKS_KEY>"
    exit 1
fi

MASTER_KEY=$1
LUKS_FILE="/secure_core.luks"
LUKS_NAME="secure_core"

echo "[*] Attempting manual offline unlock..."

printf "%s" "$MASTER_KEY" | cryptsetup luksOpen "$LUKS_FILE" "$LUKS_NAME" -d -

if [ $? -eq 0 ]; then
    echo "[*] Unlock successful!"

    echo "[*] Deriving hardware key for future offline boots..."

    HW_KEY=$(python3 - <<'PYEOF'
import hashlib, subprocess, re, sys

def _read_eeprom(bus, addr):
    """Read bytes from an I2C EEPROM address, stopping at first 0x00."""
    try:
        raw = subprocess.check_output(
            "i2cdump -y -r 0x00-0x0f %d 0x%02x b" % (bus, addr),
            shell=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return b""
    result = []
    for line in raw.splitlines():
        m = re.match(rb'^\s*[0-9a-f]+:\s+((?:[0-9a-f]{2}\s*)+)', line)
        if not m:
            continue
        for token in m.group(1).split():
            val = int(token, 16)
            if val == 0x00:
                return bytes(result)
            if val != 0xff:
                result.append(val)
    return bytes(result)

def _read_nvme_serial():
    try:
        with open("/sys/class/block/nvme0n1/device/serial") as f:
            return f.read().strip().encode("ascii")
    except (OSError, IOError):
        return b""

eeprom = _read_eeprom(0, 0x50)
nvme   = _read_nvme_serial()
salt   = _read_eeprom(0, 0x52)
if not salt:
    salt = b"opengnarbox-lwlx-v1-a6ebf01c"

if not nvme:
    sys.exit(1)

combined = (eeprom + b"|" + nvme) if eeprom else nvme

key = hashlib.pbkdf2_hmac(
    "sha256",
    combined,
    salt=salt,
    iterations=200000,
    dklen=64,
)
print(key.hex(), end="")
PYEOF
)

    if [ -z "$HW_KEY" ]; then
        echo "[!] Hardware key derivation failed — NVMe serial unavailable. Skipping key binding."
    else
        printf "%s" "$HW_KEY" > /tmp/new_hw.key
        printf "%s" "$MASTER_KEY" | cryptsetup luksAddKey "$LUKS_FILE" /tmp/new_hw.key -d -
        dd if=/dev/zero of=/tmp/new_hw.key bs=1 count=128 2>/dev/null
        rm -f /tmp/new_hw.key
        echo "[*] Hardware key added."
    fi

    touch /openfirmware/unlocked.flag
    echo "[*] Boot loop signaled. The system will now resume initialization."
else
    echo "[!] Decryption failed. Incorrect master key."
fi