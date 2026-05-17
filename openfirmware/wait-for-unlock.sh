#!/bin/bash
# OpenGNARBOX Boot Loop & Unlock Handler

LUKS_FILE="/secure_core.luks"
LUKS_NAME="secure_core"
MOUNT_POINT="/mnt/secure"
TMP_HW_KEY="/tmp/hw_unlock.key"

echo "Starting OpenGNARBOX Boot Loop..."

mkdir -p "$MOUNT_POINT"

# ── Helper: derive hardware key (must match activation.py exactly) ───────────
# activation.py uses:
#   eeprom_0x50 = i2cdump 0x50 up to first 0x00  
#   nvme        = /sys/class/block/nvme0n1/device/serial
#   salt        = i2cdump 0x51 up to first 0x00   
#   combined    = eeprom_0x50 + b"|" + nvme
#   key         = PBKDF2-HMAC-SHA256(combined, salt, iterations=200000, dklen=64).hex()
#
# PBKDF2 is not available in bash — shell out to Python 3.
get_hw_key() {
    python3 - <<'PYEOF'
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

eeprom = _read_eeprom(0, 0x50)   # domain binding
nvme   = _read_nvme_serial()      # secret component
salt   = _read_eeprom(0, 0x51)   # device-local salt
if not salt:
    salt = b"opengnarbox-lwlx-v1-a6ebf01c"  # fallback if 0x51 unreadable

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
}

# ── 1. Try Offline Unlock (Hardware Bound) ───────────────────────────────────
if [ -f "$LUKS_FILE" ] && [ ! -b "/dev/mapper/$LUKS_NAME" ]; then
    /usr/bin/oled-echo -b -- "Checking" "Hardware Lock"
    HW_KEY=$(get_hw_key)

    if [ -z "$HW_KEY" ]; then
        echo "[!] Hardware key derivation failed — NVMe serial unavailable."
    else
        echo "[*] HWID-derived key: ${HW_KEY:0:16}..."

        printf "%s" "$HW_KEY" > "$TMP_HW_KEY"

        cryptsetup luksOpen --key-file "$TMP_HW_KEY" "$LUKS_FILE" "$LUKS_NAME" 2>/dev/null

        if [ $? -eq 0 ]; then
            echo "[*] Offline unlock successful!"
            touch /openfirmware/unlocked.flag
        else
            echo "[!] Offline unlock failed (first boot or cloned SD)."
        fi

        dd if=/dev/zero of="$TMP_HW_KEY" bs=1 count=128 2>/dev/null
        rm -f "$TMP_HW_KEY"
    fi
fi

# ── 2. Wait for Captive Portal Unlock if not unlocked ────────────────────────
if [ ! -f "/openfirmware/unlocked.flag" ]; then
    /usr/bin/oled-echo -b -- "WAITING FOR" "ACTIVATION"

    python3 /openfirmware/activation.py &
    PORTAL_PID=$!

    while [ ! -f "/openfirmware/unlocked.flag" ]; do
        sleep 2
    done

    echo "[*] Unlocked flag detected!"
    kill "$PORTAL_PID" 2>/dev/null || true
    wait "$PORTAL_PID" 2>/dev/null || true
fi

# ── 3. Mount and Resume Execution ────────────────────────────────────────────
if [ -b "/dev/mapper/$LUKS_NAME" ]; then
    /usr/bin/oled-echo -b -- "Mounting" "Secure Core"

    if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        mount /dev/mapper/$LUKS_NAME "$MOUNT_POINT"
        echo "[*] Mounted $LUKS_NAME at $MOUNT_POINT"
    else
        echo "[*] $MOUNT_POINT already mounted"
    fi

    systemctl daemon-reload
    systemctl restart syslinkd 2>/dev/null || true
    systemctl restart docker 2>/dev/null || true

    if [ -f "$MOUNT_POINT/openfirmware/init.sh" ]; then
        echo "[*] Running init.sh..."
        bash "$MOUNT_POINT/openfirmware/init.sh"
    else
        echo "WARNING: init.sh not found in secure mount"
    fi
else
    echo "CRITICAL ERROR: LUKS volume is not available but flag was set!"
    /usr/bin/oled-echo -b -- "SYSTEM" "HALTED"
fi