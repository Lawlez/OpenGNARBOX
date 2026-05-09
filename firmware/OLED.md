`oled-echo` is a standalone CLI tool. From the scripts we can see:

Usage patterns:
bash
# Big text (large font, few lines)
`oled-echo -b "HELLO WORLD"`
`oled-echo -b -- "LINE 1" "LINE 2" "LINE 3"`
# Small text (small font, ~7 lines, 21 chars wide)
`oled-echo -s -- "Line 1" "Line 2" "Line 3" "" "Line 5" "Line 6" "Line 7"`
# Suppress output
`oled-echo -b "BOOTING" >/dev/null`
How to use it once you have SSH:
# Show a custom boot screen
`oled-echo -b -- "OpenGNARBOX" "v1.0"`
# Show system status
```
oled-echo -s -- "OpenGNARBOX OS" "" "IP: $(hostname -I)" "Up: $(uptime -p)" "" "SSH: active" "$(date '+%H:%M %b %d')"
```
Auto-display on boot:
You could add it to a startup script or systemd service. Create /mnt/outerroot/etc/systemd/system/oled-boot.service:
```ini
[Unit]
Description=OLED Boot Message
After=network-online.target dropbear.service
[Service]
Type=oneshot
ExecStart=/usr/bin/oled-echo -b -- "OpenGNAR" "READY"
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
```
/usr/bin/oled-echo -s -- "" "" "     OpenGNARBOX" "" "     Reclaim your" "     Hardware" "" "     lwlx."
Note: oled-echo talks to the OLED via SPI (/dev/spidev2.0). It works as a host-level binary, no Docker needed.
