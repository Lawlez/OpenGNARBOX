#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# OpenGNARBOX Activation Captive Portal
# Requires: Python 3.5+, OpenSSL 1.0.2+

import http.server
import json
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import os
import base64
import hashlib
import ssl
import time
import logging

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_PATH = "/tmp/activation.log"
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("activation")

PORT = 80
LICENSE_SERVER = "https://opengnar-lic.lwlx.xyz"
LUKS_FILE = "/secure_core.luks"
LUKS_NAME = "secure_core"
FLAG_PATH = "/openfirmware/unlocked.flag"

# Temp file paths (centralised so cleanup never misses one)
TMP_PRIVATE_KEY = "/tmp/private.pem"
TMP_PUBLIC_KEY  = "/tmp/public.pem"
TMP_ENCRYPTED   = "/tmp/encrypted.bin"
TMP_MASTER_KEY  = "/tmp/master.key"
TMP_HW_KEY      = "/tmp/new_hw.key"
TMP_WPA_CONF    = "/tmp/wpa_supplicant.conf"

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
    <title>OpenGNARBOX Activation</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #1a1a1a; color: #fff;
               display: flex; justify-content: center; align-items: center;
               height: 100vh; margin: 0; }
        .card { background: #2a2a2a; padding: 2rem; border-radius: 8px;
                width: 100%%; max-width: 400px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        input  { width: 100%%; padding: 10px; margin-top: 5px;
                 margin-bottom: 15px; border-radius: 4px;
                 border: 1px solid #444; background: #333; color: white;
                 box-sizing: border-box; }
        button { width: 100%%; padding: 12px; background: #007bff;
                 color: white; border: none; border-radius: 4px;
                 cursor: pointer; font-weight: bold; }
        button:hover { background: #0056b3; }
        h2 { margin-top: 0; color: #007bff; }
    </style>
</head>
<body>
    <div class="card">
        <h2>OpenGNARBOX</h2>
        <p>Connect to your home Wi-Fi to activate this firmware.</p>
        <form method="POST">
            <label>Wi-Fi SSID</label>
            <input type="text" name="ssid" required>

            <label>Wi-Fi Password</label>
            <input type="password" name="password" required>

            <label>License Key</label>
            <input type="text" name="license_key" required>

            <button type="submit">Activate Device</button>
        </form>
    </div>
</body>
</html>
"""

# ── Helpers ──────────────────────────────────────────────────────────────────

def oled(line1, line2=""):
    """Show a two-line status message on the OLED."""
    if line2:
        subprocess.call(["/usr/bin/oled-echo", "-b", "--", line1, line2])
    else:
        subprocess.call(["/usr/bin/oled-echo", "-b", "--", line1])


def run_cmd(cmd):
    """Run a shell command, log it, and return the exit code."""
    log.info("CMD: %s", cmd)
    print("Executing: " + cmd)
    return subprocess.call(cmd, shell=True)


def secure_delete(*paths):
    """Overwrite files with zeros then unlink — best-effort scrub."""
    for p in paths:
        try:
            sz = os.path.getsize(p)
            with open(p, "wb") as f:
                f.write(b"\x00" * sz)
            os.unlink(p)
        except OSError:
            pass


def get_hardware_id():
    """Derive a deterministic hardware fingerprint from mlan0 + uap0 MACs."""
    try:
        mlan_mac = subprocess.check_output(
            "cat /sys/class/net/mlan0/address",
            shell=True,
        ).strip().decode("utf-8", errors="replace")
        uap_mac = subprocess.check_output(
            "cat /sys/class/net/uap0/address",
            shell=True,
        ).strip().decode("utf-8", errors="replace")
        return "GBX-%s-%s" % (
            mlan_mac.replace(":", ""),
            uap_mac.replace(":", ""),
        )
    except Exception:
        return "GBX-UNKNOWN-HARDWARE"


def derive_hw_key(hwid):
    """SHA-256 of the hardware ID — used as the offline LUKS passphrase.

    Done in pure Python so we avoid shell-injection via hwid.
    """
    if isinstance(hwid, str):
        hwid = hwid.encode("utf-8")
    return hashlib.sha256(hwid).hexdigest()


# ── Wi-Fi ────────────────────────────────────────────────────────────────────

def connect_wifi(ssid, password):
    """Write a wpa_supplicant config and connect mlan0 to a Wi-Fi network."""
    # Escape any embedded double-quotes in user input
    safe_ssid = ssid.replace('"', '\\"')
    safe_pass = password.replace('"', '\\"')

    wpa_conf = (
        'network={\n'
        '    ssid="%s"\n'
        '    psk="%s"\n'
        '}\n'
    ) % (safe_ssid, safe_pass)

    with open(TMP_WPA_CONF, "w") as f:
        f.write(wpa_conf)

    # Bring up the managed Wi-Fi interface (mlan0) and connect
    run_cmd("killall wpa_supplicant 2>/dev/null || true")
    run_cmd("ip link set mlan0 up")
    run_cmd("wpa_supplicant -B -i mlan0 -c " + TMP_WPA_CONF)
    time.sleep(5)
    run_cmd("udhcpc -i mlan0 -q")


# ── RSA key generation ───────────────────────────────────────────────────────

def generate_keypair():
    """Generate a fresh 2048-bit RSA keypair via OpenSSL."""
    run_cmd("openssl genrsa -out %s 2048" % TMP_PRIVATE_KEY)
    run_cmd("openssl rsa -in %s -pubout -out %s" % (TMP_PRIVATE_KEY, TMP_PUBLIC_KEY))
    with open(TMP_PUBLIC_KEY, "r") as f:
        return f.read()


# ── Server communication ────────────────────────────────────────────────────

def request_master_key(hwid, license_key, pubkey_pem):
    """POST to the license server and return the JSON response dict.

    TLS cert verification is skipped because the GNARBOX's CA bundle is
    from 2018 and doesn't trust modern Cloudflare certs.  This is safe
    because the payload is already RSA-OAEP encrypted end-to-end.
    """
    payload = json.dumps({
        "hwid": hwid,
        "license_key": license_key,
        "pubkey_pem": pubkey_pem,
    }).encode("utf-8")

    req = urllib.request.Request(
        LICENSE_SERVER,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OpenGNARBOX-Activation/1.0",
        },
    )

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    log.info("POST %s (%d bytes)", LICENSE_SERVER, len(payload))
    try:
        response = urllib.request.urlopen(req, timeout=15, context=ctx)
        body = response.read().decode("utf-8")
        log.info("Response %d: %s", response.getcode(), body[:200])
        return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        log.error("HTTP %d: %s", e.code, err_body[:500])
        raise


# ── Decryption ───────────────────────────────────────────────────────────────

def decrypt_master_key(encrypted_b64):
    """Decrypt the RSA-OAEP (SHA-1) encrypted master key using OpenSSL.

    The server (index.py) encrypts with OAEP / SHA-1 / MGF1-SHA-1.
    OpenSSL 1.0.2's `rsautl -oaep` uses SHA-1 by default which matches.
    """
    with open(TMP_ENCRYPTED, "wb") as f:
        f.write(base64.b64decode(encrypted_b64))

    rc = run_cmd(
        "openssl rsautl -decrypt -oaep"
        " -inkey %s"
        " -in %s"
        " -out %s"
        % (TMP_PRIVATE_KEY, TMP_ENCRYPTED, TMP_MASTER_KEY)
    )
    if rc != 0:
        raise RuntimeError("openssl rsautl decrypt failed (exit %d)" % rc)

    with open(TMP_MASTER_KEY, "r") as f:
        return f.read()


# ── LUKS operations ─────────────────────────────────────────────────────────

def open_luks(master_key):
    """Open the LUKS container with the master key.

    Uses --key-file to pass the exact key bytes.  Piping via stdin
    (passphrase mode) causes cryptsetup to apply newline-termination
    and other processing that corrupts the key.
    """
    # Debug: hex-dump the key file so we can verify exact bytes
    try:
        with open(TMP_MASTER_KEY, "rb") as f:
            raw = f.read()
        log.info("KEY FILE: %d bytes, hex=%s, repr=%r", len(raw), raw.hex(), raw)
    except Exception as e:
        log.error("Cannot read key file: %s", e)

    cmd = "cryptsetup luksOpen --key-file %s %s %s" % (
        TMP_MASTER_KEY, LUKS_FILE, LUKS_NAME
    )
    log.info("CMD: %s", cmd)
    print("Executing: " + cmd)
    p = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE)
    _, stderr = p.communicate()
    if stderr:
        log.error("cryptsetup stderr: %s", stderr.decode("utf-8", errors="replace"))
    log.info("cryptsetup exit code: %d", p.returncode)
    return p.returncode == 0


def bind_hardware_key(master_key, hwid):
    """Add a hardware-derived LUKS key so the device can boot offline."""
    hw_key = derive_hw_key(hwid)
    with open(TMP_HW_KEY, "w") as f:
        f.write(hw_key)

    # --key-file supplies the existing passphrase (master key)
    # positional arg is the new key file to add
    cmd = "cryptsetup luksAddKey --key-file %s %s %s" % (
        TMP_MASTER_KEY, LUKS_FILE, TMP_HW_KEY
    )
    log.info("CMD: %s", cmd)
    print("Executing: " + cmd)
    p = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE)
    _, stderr = p.communicate()
    if stderr:
        log.error("luksAddKey stderr: %s", stderr.decode("utf-8", errors="replace"))
    log.info("luksAddKey exit code: %d", p.returncode)
    return p.returncode == 0


# ── HTTP handler ─────────────────────────────────────────────────────────────

def _parse_post_body(handler):
    """Parse URL-encoded POST body (replaces deprecated cgi.FieldStorage).

    Returns a dict of {field_name: value}.
    """
    content_length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(content_length).decode("utf-8")
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
    # parse_qs returns lists; flatten to single values
    return {k: v[0] for k, v in parsed.items()}


class ActivationHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

    def do_POST(self):
        fields = _parse_post_body(self)

        ssid = fields.get("ssid", "").strip()
        password = fields.get("password", "").strip()
        license_key = fields.get("license_key", "").strip()

        # Reject empty / probe requests before doing anything destructive
        if not ssid or not password or not license_key:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h2>Missing fields</h2>"
                b"<p>Please fill in SSID, password, and license key.</p>"
                b'<p><a href="/">Go back</a></p>'
            )
            return

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<h2>Activating&hellip; Please check the OLED screen.</h2>"
            b"<p>This may take up to 60 seconds.</p>"
        )

        try:
            # 1. Connect to Wi-Fi
            oled("Connecting", "To Wi-Fi")
            log.info("STEP 1: Connecting to Wi-Fi SSID=%s", ssid)
            connect_wifi(ssid, password)
            log.info("STEP 1: Wi-Fi connected")

            # 2. Generate RSA keypair
            oled("Generating", "Keys")
            log.info("STEP 2: Generating RSA keypair")
            pubkey_pem = generate_keypair()
            log.info("STEP 2: Keypair generated, pubkey=%d bytes", len(pubkey_pem))

            # 3. Contact the license server
            oled("Contacting", "Server")
            hwid = get_hardware_id()
            log.info("STEP 3: HWID=%s, contacting server", hwid)
            resp = request_master_key(hwid, license_key, pubkey_pem)
            log.info("STEP 3: Server response keys: %s", list(resp.keys()))

            if "error" in resp:
                log.error("STEP 3: Server returned error: %s", resp["error"])
                oled("ACTIVATION", "FAILED")
                return

            # 4. Decrypt the RSA-OAEP payload
            oled("Decrypting", "LUKS Payload")
            log.info("STEP 4: Decrypting, encrypted_key=%d chars",
                      len(resp.get("encrypted_key", "")))
            master_key = decrypt_master_key(resp["encrypted_key"])
            log.info("STEP 4: Decrypted master key: len=%d, hex=%s...",
                      len(master_key), master_key[:8].encode("utf-8").hex())

            # Debug: verify files exist before LUKS
            for f in [TMP_MASTER_KEY, TMP_PRIVATE_KEY, LUKS_FILE]:
                exists = os.path.exists(f)
                sz = os.path.getsize(f) if exists else -1
                log.info("  FILE %s exists=%s size=%d", f, exists, sz)

            # 5. Open LUKS
            oled("Opening", "LUKS Volume")
            log.info("STEP 5: Opening LUKS %s as %s", LUKS_FILE, LUKS_NAME)
            if not open_luks(master_key):
                log.error("STEP 5: cryptsetup luksOpen FAILED")
                # Try to show what cryptsetup thinks
                run_cmd("cryptsetup luksDump %s 2>&1 | head -20" % LUKS_FILE)
                oled("LUKS OPEN", "FAILED")
                return
            log.info("STEP 5: LUKS opened successfully")

            # 6. Bind a hardware-derived key for offline boots
            oled("Binding to", "Hardware")
            log.info("STEP 6: Binding HW key for HWID=%s", hwid)
            if not bind_hardware_key(master_key, hwid):
                log.error("STEP 6: luksAddKey FAILED (non-fatal, continuing)")
            else:
                log.info("STEP 6: HW key bound successfully")

            # 7. Signal success
            with open(FLAG_PATH, "w") as f:
                f.write("OK")
            log.info("STEP 7: Flag written to %s", FLAG_PATH)

            oled("ACTIVATION", "SUCCESS")
            log.info("STEP 8: Activation complete, exiting portal")

            # Terminate the activation portal — os._exit is reliable on
            # embedded Python where _thread.interrupt_main may not work.
            os._exit(0)

        except Exception as e:
            log.error("Activation error: %s: %s", type(e).__name__, str(e))
            print("Activation error: " + str(e))
            oled("ERROR", str(e)[:16])

        finally:
            # Always cleanup sensitive material, even on failure
            log.info("CLEANUP: scrubbing temp files")
            secure_delete(
                TMP_MASTER_KEY, TMP_HW_KEY, TMP_PRIVATE_KEY,
                TMP_PUBLIC_KEY, TMP_ENCRYPTED, TMP_WPA_CONF,
            )
            log.info("CLEANUP: done")

    def log_message(self, fmt, *args):
        """Suppress default stderr logging — we print our own."""
        pass


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting Captive Portal on port %d..." % PORT)
    server = http.server.HTTPServer(("", PORT), ActivationHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

