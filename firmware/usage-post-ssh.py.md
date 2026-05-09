# Full run (default)
python3 firmware/post-ssh.py
# Custom WiFi
python3 firmware/post-ssh.py --ssid "MyGNARBOX" --pass "secretpass123"
# Verify only (no changes)
python3 firmware/post-ssh.py --verify-only
# Skip specific phases
python3 firmware/post-ssh.py --skip-docker --skip-wifi