#!/usr/bin/env python3
"""
OpenGNARBOX Post-SSH Automation Script
======================================
Automates the initial setup of a freshly flashed GNARBOX 2.0 device
over SSH. Removes bloat, configures WiFi, installs OLED diagnostics,
and verifies the system state.

Uses the system ssh binary for compatibility.

Usage:
    python3 post-ssh.py [--host 172.16.0.1] [--key ~/.ssh/id_gnarbox]
                        [--ssid OpenGNARBOX] [--pass reclaimGNARBOX!]
                        [--dry-run]
"""

import argparse
import subprocess
import sys
import time
import os

# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_HOST = "172.16.0.1"
DEFAULT_KEY  = os.path.expanduser("~/.ssh/id_gnarbox")
DEFAULT_USER = "root"
DEFAULT_SSID = "OpenGNARBOX"
DEFAULT_PASS = "reclaimGNARBOX!"

# Docker services to remove (swarm service names)
SERVICES_TO_REMOVE = [
    #"services_stack_grab",
    #"services_stack_overlookd",
    #"services_stack_tapperd",
]

# Docker images to remove after service deletion
IMAGES_TO_REMOVE = [
    #"gnarbox/grab:2.8.0.1747",
    #"gnarbox/overlook:2.8.0.1747",
    #"gnarbox/tapper:2.8.0.1747",
]

# ANSI colors for output
class C:
    HEADER  = "\033[95m"
    BLUE    = "\033[94m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    BOLD    = "\033[1m"
    END     = "\033[0m"

def banner():
    print(f"""
{C.CYAN}{C.BOLD}
   ██████╗ ██████╗ ███████╗███╗   ██╗
  ██╔═══██╗██╔══██╗██╔════╝████╗  ██║
  ██║   ██║██████╔╝█████╗  ██╔██╗ ██║
  ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║
  ╚██████╔╝██║     ███████╗██║ ╚████║
   ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝
   ██████╗ ███╗   ██╗ █████╗ ██████╗ ██████╗  ██████╗ ██╗  ██╗
  ██╔════╝ ████╗  ██║██╔══██╗██╔══██╗██╔══██╗██╔═══██╗╚██╗██╔╝
  ██║  ███╗██╔██╗ ██║███████║██████╔╝██████╔╝██║   ██║ ╚███╔╝
  ██║   ██║██║╚██╗██║██╔══██║██╔══██╗██╔══██╗██║   ██║ ██╔██╗
  ╚██████╔╝██║ ╚████║██║  ██║██║  ██║██████╔╝╚██████╔╝██╔╝ ██╗
   ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝╚═╝  ╚═╝
{C.END}
{C.YELLOW}  Post-SSH Automation — CyberTap Security{C.END}
""")


def log_step(msg):
    print(f"\n{C.BOLD}{C.BLUE}[*]{C.END} {C.BOLD}{msg}{C.END}")

def log_ok(msg):
    print(f"  {C.GREEN}[✓]{C.END} {msg}")

def log_warn(msg):
    print(f"  {C.YELLOW}[!]{C.END} {msg}")

def log_fail(msg):
    print(f"  {C.RED}[✗]{C.END} {msg}")

def log_info(msg):
    print(f"  {C.CYAN}[i]{C.END} {msg}")

def log_cmd(msg):
    print(f"  {C.HEADER}  $ {msg}{C.END}")


class SSHSession:
    """Wraps the system ssh binary for Dropbear-compatible remote execution.
         This class uses the actual ssh CLI binary.
    """

    def __init__(self, host, user, keyfile):
        self.host = host
        self.user = user
        self.keyfile = keyfile
        self._ssh_base = [
            "ssh",
            "-i", self.keyfile,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=15",
            "-o", "BatchMode=yes",
            f"{self.user}@{self.host}",
        ]

    def run(self, cmd, timeout=30):
        """Execute a remote command and return stdout."""
        try:
            result = subprocess.run(
                self._ssh_base + [cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            # Combine stdout and stderr,some busybox comands write to stderr
            output = result.stdout.strip()
            if result.returncode != 0 and not output:
                output = result.stderr.strip()
            return output
        except subprocess.TimeoutExpired:
            return "[TIMEOUT]"
        except Exception as e:
            return f"[ERROR: {e}]"

    def test(self):
        """test the connection with a simple command."""
        return self.run("echo CONNECTED")

    def close(self):
        """noop for subprocess-based sessions."""
        pass


def run_cmd(shell, cmd, quiet=False):
    """Execute a command over SSH and return output."""
    if not quiet:
        log_cmd(cmd)
    return shell.run(cmd)


def connect_ssh(host, user, keyfile):
    """Establish SSH connection using the system ssh binary."""
    log_step(f"Connecting to {user}@{host}")

    if not os.path.exists(keyfile):
        log_fail(f"SSH key not found: {keyfile}")
        sys.exit(1)

    session = SSHSession(host, user, keyfile)
    result = session.test()

    if "CONNECTED" in result:
        log_ok(f"Connected to {host}")
        return session
    else:
        log_fail(f"SSH connection failed: {result}")
        sys.exit(1)


# ─── Phase 1: OLED Boot Diagnostic Script ─────────────────────────────────────

OLED_BOOT_SCRIPT = r'''#!/bin/sh
sleep 5

# Check dropbear binary
DB_STATUS="FAIL"
[ -x /usr/sbin/dropbear ] && DB_STATUS="BIN OK"

# Check port 22
PORT_STATUS="CLOSED"
netstat -tln 2>/dev/null | grep -q ":22 " && PORT_STATUS="OPEN"

# Get IP
IP_ADDR=$(ip -4 addr show 2>/dev/null | grep -oE '172\.[0-9.]+' | head -1)
[ -z "$IP_ADDR" ] && IP_ADDR="no ip"

/usr/bin/oled-echo -s -- \
  "OpenGNARBOX v1.0" \
  "" \
  "SSH: $DB_STATUS" \
  "P22: $PORT_STATUS" \
  "IP:  $IP_ADDR" \
  "" \
  "$(date +%H:%M)"
'''

OLED_SERVICE_UNIT = """[Unit]
Description=OLED Boot Message + SSH Debug
After=network-online.target dropbear.service shivad.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/oled-boot.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""


def install_oled_diagnostics(shell):
    """Install the OLED boot diagnostic script and systemd service."""
    log_step("Installing OLED boot diagnostics")

    # Check if already installed
    check = run_cmd(shell, "test -f /usr/local/bin/oled-boot.sh && echo EXISTS || echo MISSING", quiet=True)
    if "EXISTS" in check:
        log_warn("oled-boot.sh already exists — overwriting")

    # Create directory
    run_cmd(shell, "mkdir -p /usr/local/bin")
    log_ok("Created /usr/local/bin/")

    #write the OLED boot script
    # use base64 to avoid shell escaping hell with heredocs over SSH
    import base64
    script_b64 = base64.b64encode(OLED_BOOT_SCRIPT.encode()).decode()
    run_cmd(shell, f"echo '{script_b64}' | base64 -d > /usr/local/bin/oled-boot.sh")
    run_cmd(shell, "chmod +x /usr/local/bin/oled-boot.sh")
    log_ok("Wrote /usr/local/bin/oled-boot.sh")

    # Write the systemd service
    service_b64 = base64.b64encode(OLED_SERVICE_UNIT.encode()).decode()
    run_cmd(shell, f"echo '{service_b64}' | base64 -d > /etc/systemd/system/oled-boot.service")
    log_ok("Wrote /etc/systemd/system/oled-boot.service")

    # Enable the service
    run_cmd(shell, "ln -sf /etc/systemd/system/oled-boot.service "
                   "/etc/systemd/system/multi-user.target.wants/oled-boot.service")
    log_ok("Enabled oled-boot.service")


# ─── Phase 2: Remove Docker Bloat ─────────────────────────────────────────────

def remove_docker_bloat(shell):
    """Remove unnecessary Docker swarm services and their images."""
    log_step("Removing Docker bloat services")

    #shows current state
    log_info("Current Docker services:")
    output = run_cmd(shell, 'docker service ls --format "table {{.Name}}\t{{.Image}}\t{{.Replicas}}"')
    for line in output.splitlines():
        print(f"    {line}")

    # Remove swarm services
    for svc in SERVICES_TO_REMOVE:
        result = run_cmd(shell, f"docker service rm {svc} 2>&1 || echo 'NOT_FOUND'")
        if "NOT_FOUND" in result or "not found" in result.lower():
            log_warn(f"Service {svc} not found (already removed?)")
        else:
            log_ok(f"Removed service: {svc}")

    # Wait for containers to stop
    log_info("Waiting for containers to stop...")
    time.sleep(5)

    # Backup the stack definition BEFORE modifying
    log_step("Backing up and cleaning stack definition")
    stack_file = "/app_data/shiva/althing/stacks/mosh/services_stack_prod.yml"
    run_cmd(shell, f"cp {stack_file} {stack_file}.bak 2>/dev/null || true")
    log_ok("Backed up services_stack_prod.yml")

    # Remove the service definitions from the YAML using awk
    # sed leaves empty keys (e.g. "  tapperd:") which breaks YAML parsing.
    # awk properly skips the entire block from key to next sibling key.
    # IMPORTANT: grab is the LAST service before the top-level `networks:` block.
    # The awk pattern `/^  [a-z]/` won't match `networks:` (0-indent), so awk
    # will eat everything from `grab:` to EOF including the networks block.
    # We re-append it after cleanup.
    log_info("Cleaning service definitions from stack YAML...")
    stack_tmp = "/tmp/stack_clean.yml"
    for svc_short in ["grab", "overlookd", "tapperd"]:
        run_cmd(shell,
            f"awk '/^  {svc_short}:/{{skip=1; next}} /^  [a-z]/{{skip=0}} /^[a-z]/{{skip=0}} !skip' "
            f"{stack_file} > {stack_tmp} && mv {stack_tmp} {stack_file}",
            quiet=True)

    # Ensure the top-level networks: block exists (awk may have eaten it)
    # If `networks:` (0-indent) was removed but its children (`  ingress-net:`,
    # `  outside:`) survived, they're now orphaned at service level.
    # Strip orphans first, then re-append the complete block.
    has_networks = run_cmd(shell, f"grep -c '^networks:' {stack_file}", quiet=True)
    if has_networks.strip() == "0":
        log_warn("networks: block was removed by awk — fixing")
        # Remove orphaned network entries that look like services
        for orphan in ["ingress-net", "outside"]:
            run_cmd(shell,
                f"awk '/^  {orphan}:/{{skip=1; next}} /^  [a-z]/{{skip=0}} /^[a-z]/{{skip=0}} !skip' "
                f"{stack_file} > {stack_tmp} && mv {stack_tmp} {stack_file}",
                quiet=True)
        # Append the complete networks block
        networks_block = (
            "networks:\\n"
            "  ingress-net:\\n"
            "    external:\\n"
            "      name: ingress-net\\n"
            "  outside:\\n"
            "    external:\\n"
            "      name: host\\n"
        )
        run_cmd(shell, f'printf "\\n{networks_block}" >> {stack_file}', quiet=True)
        log_ok("Restored networks: block")

    # Verify the YAML still has the expected structure
    check = run_cmd(shell, f"head -3 {stack_file}", quiet=True)
    net_check = run_cmd(shell, f"grep -c '^networks:' {stack_file}", quiet=True)
    if 'version' in check and 'services' in check and net_check.strip() != "0":
        log_ok("Cleaned service definitions from stack YAML")
    else:
        log_fail("Stack YAML may be corrupted — restoring from backup")
        run_cmd(shell, f"cp {stack_file}.bak {stack_file}")
        log_warn("Restored services_stack_prod.yml from backup")

    # Remove Docker images
    log_step("Removing Docker images")
    for img in IMAGES_TO_REMOVE:
        result = run_cmd(shell, f"docker image rm {img} 2>&1 || echo 'NOT_FOUND'")
        if "NOT_FOUND" in result or "No such image" in result:
            log_warn(f"Image {img} not found (already removed?)")
        else:
            log_ok(f"Removed image: {img}")

    # Prune
    run_cmd(shell, "docker system prune -f")
    log_ok("Docker system pruned")

    # Show remaining state
    log_info("Remaining Docker services:")
    output = run_cmd(shell, 'docker service ls --format "table {{.Name}}\t{{.Image}}"')
    for line in output.splitlines():
        print(f"    {line}")


# ─── Phase 3: Remove Mender ───────────────────────────────────────────────────

def remove_mender(shell):
    """Completely remove all Mender OTA update artifacts."""
    log_step("Removing Mender OTA system")

    # Binaries
    for f in ["/usr/bin/mender", "/usr/bin/fw_printenv", "/usr/bin/fw_setenv"]:
        result = run_cmd(shell, f"rm -f {f} && echo OK || echo FAIL", quiet=True)
        if "OK" in result:
            log_ok(f"Removed {f}")

    # Config directories
    for d in ["/etc/mender", "/app_data/mender", "/data/mender"]:
        run_cmd(shell, f"rm -rf {d} 2>/dev/null", quiet=True)
        log_ok(f"Removed {d}/")

    # App data files
    run_cmd(shell, "rm -f /app_data/mender_grubenv.config", quiet=True)
    log_ok("Removed mender_grubenv.config")

    # Service files
    for svc in [
        "/etc/systemd/system/mender.service",
        "/etc/systemd/system/mender-data-dir.service",
        "/lib/systemd/system/mender.service",
    ]:
        run_cmd(shell, f"rm -f {svc} 2>/dev/null", quiet=True)

    run_cmd(shell, "systemctl daemon-reload")
    log_ok("Removed Mender service files and reloaded systemd")


# ─── Phase 4: Disable Logging Bloat ──────────────────────────────────────────

def disable_logging_bloat(shell):
    """Stop and disable unnecessary GNARBOX logging services."""
    log_step("Disabling logging bloat")

    run_cmd(shell, "systemctl stop extra-logs mcu-logs 2>/dev/null || true")
    result = run_cmd(shell, "systemctl disable extra-logs mcu-logs 2>&1")
    log_ok("Stopped and disabled extra-logs, mcu-logs")

    # Clear old logs
    run_cmd(shell, "rm -rf /app_data/logs/* 2>/dev/null || true")
    log_ok("Cleared /app_data/logs/")


# ─── Phase 5: WiFi Reconfiguration ────────────────────────────────────────────

def reconfigure_wifi(shell, new_ssid, new_pass):
    """Backup and reconfigure WiFi SSID and password on BOTH config files."""
    log_step("Reconfiguring WiFi")

    # Backup current config
    log_info("Current WiFi configuration:")
    current = run_cmd(shell, "grep -E '^(ssid|wpa_passphrase)=' /app_data/hostapd/hostapd.conf")
    for line in current.splitlines():
        print(f"    {line}")

    run_cmd(shell, "cp /app_data/hostapd/hostapd.conf /app_data/hostapd/hostapd.conf.bak")
    run_cmd(shell, "cp /etc/hostapd.conf /etc/hostapd.conf.bak")
    log_ok("Backed up both hostapd.conf files")

    # Change SSID and password in BOTH files
    # CRITICAL: Must edit both, syslinkd syncs between them on boot
    for conf in ["/app_data/hostapd/hostapd.conf", "/etc/hostapd.conf"]:
        run_cmd(shell, f"sed -i 's/^ssid=.*/ssid={new_ssid}/' {conf}")
        run_cmd(shell, f"sed -i 's/^wpa_passphrase=.*/wpa_passphrase={new_pass}/' {conf}")
    log_ok(f"Set SSID={new_ssid} password={new_pass} in both configs")

    log_warn(f"WiFi will change on next reboot!")
    log_warn(f"Connect to SSID '{new_ssid}' with password '{new_pass}'")


# ─── Phase 6: Safety Checks ──────────────────────────────────────────────────

def safety_checks(shell):
    """Verify critical files exist that must NEVER be deleted."""
    log_step("Running safety checks")

    # firstbooted-* files must exist
    # Deleting them triggers re-provisioning and regenerates WiFi password...
    latch_files = [
        "/app_data/firstbooted-fs",
        "/app_data/firstbooted-functional",
        "/app_data/firstbooted-smoke",
    ]
    all_ok = True
    for f in latch_files:
        result = run_cmd(shell, f"test -f {f} && echo EXISTS || echo MISSING", quiet=True)
        if "MISSING" in result:
            log_fail(f"CRITICAL: {f} is MISSING! Restoring...")
            run_cmd(shell, f"touch {f}")
            log_warn(f"Restored {f} (empty latch file)")
            all_ok = False
        else:
            log_ok(f"{f} exists")

    if not all_ok:
        log_warn("Latch files were missing — WiFi password may have been regenerated on last boot!")

    return all_ok


# ─── Phase 7: Verification ───────────────────────────────────────────────────

def verify_system(shell):
    """Run comprehensive verification of all changes."""
    log_step("Running verification")

    checks = {
        "Dropbear SSH":     "systemctl is-active dropbear 2>/dev/null",
        "Docker Engine":    "systemctl is-active docker 2>/dev/null",
        "WiFi (hostapd)":   "systemctl is-active hostapd 2>/dev/null",
        "Network (syslinkd)": "systemctl is-active syslinkd 2>/dev/null",
        "OLED service":     "systemctl is-enabled oled-boot 2>/dev/null",
    }

    print()
    print(f"  {C.BOLD}{'Service':<25} {'Status':<15}{C.END}")
    print(f"  {'─' * 40}")
    for name, cmd in checks.items():
        result = run_cmd(shell, cmd, quiet=True)
        if result in ("active", "enabled"):
            print(f"  {name:<25} {C.GREEN}{result}{C.END}")
        else:
            print(f"  {name:<25} {C.RED}{result}{C.END}")

    # Check Mender is gone
    mender_check = run_cmd(shell, "which mender 2>/dev/null || echo GONE", quiet=True)
    mender_svc = run_cmd(shell, "systemctl is-enabled mender 2>/dev/null || echo disabled", quiet=True)
    print()
    if "GONE" in mender_check:
        log_ok("Mender binary: removed")
    else:
        log_fail(f"Mender binary still exists: {mender_check}")
    if "disabled" in mender_svc or "not-found" in mender_svc:
        log_ok("Mender service: disabled")
    else:
        log_fail(f"Mender service: {mender_svc}")

    # Check logging bloat
    for svc in ["extra-logs", "mcu-logs"]:
        result = run_cmd(shell, f"systemctl is-enabled {svc} 2>/dev/null || echo disabled", quiet=True)
        if "disabled" in result:
            log_ok(f"{svc}: disabled")
        else:
            log_warn(f"{svc}: {result}")

    # Docker container count
    count = run_cmd(shell, "docker ps -q | wc -l", quiet=True).strip()
    log_info(f"Running Docker containers: {count}")

    # Show remaining Docker services
    log_info("Docker swarm services:")
    output = run_cmd(shell, 'docker service ls --format "  {{.Name}} → {{.Image}} ({{.Replicas}})"', quiet=True)
    for line in output.splitlines():
        print(f"    {line}")

    # WiFi config
    print()
    log_info("WiFi configuration (/app_data/hostapd/hostapd.conf):")
    wifi = run_cmd(shell, "grep -E '^(ssid|wpa_passphrase)=' /app_data/hostapd/hostapd.conf", quiet=True)
    for line in wifi.splitlines():
        print(f"    {line}")

    log_info("WiFi configuration (/etc/hostapd.conf):")
    wifi2 = run_cmd(shell, "grep -E '^(ssid|wpa_passphrase)=' /etc/hostapd.conf", quiet=True)
    for line in wifi2.splitlines():
        print(f"    {line}")

    # OLED script check
    oled_check = run_cmd(shell, "test -x /usr/local/bin/oled-boot.sh && echo OK || echo MISSING", quiet=True)
    if "OK" in oled_check:
        log_ok("OLED boot script: installed and executable")
    else:
        log_fail("OLED boot script: missing!")

    # Shadow file check
    shadow = run_cmd(shell, "grep ^root /etc/shadow", quiet=True)
    if shadow.startswith("root::"):
        log_ok(f"Shadow: pubkey-only (no password lock)")
    elif shadow.startswith("root:*"):
        log_fail(f"Shadow: account LOCKED (root:*) — Dropbear will reject auth!")
    else:
        log_warn(f"Shadow: {shadow[:40]}...")

    # SSH key check
    key_check = run_cmd(shell, "test -f /root/.ssh/authorized_keys && echo OK || echo MISSING", quiet=True)
    if "OK" in key_check:
        key_type = run_cmd(shell, "head -1 /root/.ssh/authorized_keys | awk '{print $1}'", quiet=True)
        log_ok(f"SSH authorized_keys: present ({key_type})")
    else:
        log_fail("SSH authorized_keys: MISSING!")

    # Firstbooted latch files
    for f in ["firstbooted-fs", "firstbooted-functional", "firstbooted-smoke"]:
        result = run_cmd(shell, f"test -f /app_data/{f} && echo OK || echo MISSING", quiet=True)
        if "OK" in result:
            log_ok(f"/app_data/{f}: ✓")
        else:
            log_fail(f"/app_data/{f}: MISSING — WiFi will break on reboot!")

    # Disk usage summary
    print()
    log_info("Disk usage:")
    disk = run_cmd(shell, "df -h / /var/lib/docker /app_data /media/GNARBOX 2>/dev/null", quiet=True)
    for line in disk.splitlines():
        print(f"    {line}")

    # Memory
    mem = run_cmd(shell, "free -m | head -2", quiet=True)
    print()
    log_info("Memory:")
    for line in mem.splitlines():
        print(f"    {line}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="OpenGNARBOX Post-SSH Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"GNARBOX IP (default: {DEFAULT_HOST})")
    parser.add_argument("--key", default=DEFAULT_KEY, help=f"SSH key path (default: {DEFAULT_KEY})")
    parser.add_argument("--user", default=DEFAULT_USER, help=f"SSH user (default: {DEFAULT_USER})")
    parser.add_argument("--ssid", default=DEFAULT_SSID, help=f"New WiFi SSID (default: {DEFAULT_SSID})")
    parser.add_argument("--pass", dest="wifi_pass", default=DEFAULT_PASS,
                        help=f"New WiFi password (default: {DEFAULT_PASS})")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--skip-docker", action="store_true", help="Skip Docker cleanup phase")
    parser.add_argument("--skip-wifi", action="store_true", help="Skip WiFi reconfiguration")
    parser.add_argument("--skip-oled", action="store_true", help="Skip OLED script installation")
    parser.add_argument("--verify-only", action="store_true", help="Only run verification, no changes")

    args = parser.parse_args()

    banner()

    if args.dry_run:
        log_warn("DRY RUN MODE — no changes will be made")
        print()

    shell = connect_ssh(args.host, args.user, args.key)

    # quick system ID
    log_step("System identification")
    hostname = run_cmd(shell, "hostname", quiet=True)
    kernel = run_cmd(shell, "uname -r", quiet=True)
    os_ver = run_cmd(shell, "grep VERSION_ID /etc/os-release | cut -d= -f2 | tr -d '\"'", quiet=True)
    log_info(f"Hostname: {hostname}")
    log_info(f"Kernel:   {kernel}")
    log_info(f"OS:       GNARBOX OS {os_ver}")

    if args.verify_only:
        safety_checks(shell)
        verify_system(shell)
        shell.close()
        print(f"\n{C.GREEN}{C.BOLD}[✓] Verification complete.{C.END}\n")
        return

    if args.dry_run:
        log_warn("Dry run — skipping all modifications")
        shell.close()
        return

    # Phase 1: Safety checks FIRST
    safety_checks(shell)

    # Phase 2: OLED diag
    if not args.skip_oled:
        install_oled_diagnostics(shell)

    # Phase 3: Docker bloat removal
    if not args.skip_docker:
        remove_docker_bloat(shell)

    # Phase 4: Remove Mender
    remove_mender(shell)

    # Phase 5: Disable logging bloat
    disable_logging_bloat(shell)

    # Phase 6: WiFi reconfig
    if not args.skip_wifi:
        reconfigure_wifi(shell, args.ssid, args.wifi_pass)

    # Phase 7: Final verification
    verify_system(shell)

    # Done
    shell.close()
    print(f"""
{C.GREEN}{C.BOLD}{'═' * 60}
  OpenGNARBOX post-SSH setup complete!
{'═' * 60}{C.END}

{C.CYAN}Next steps:{C.END}
  1. Reboot:   ssh -i {args.key} {args.user}@{args.host}
               echo 1 > /sys/bus/i2c/devices/i2c-GBX0001:00/system_state/cold_reboot
  2. Reconnect to WiFi SSID: {C.BOLD}{args.ssid}{C.END}
     Password: {C.BOLD}{args.wifi_pass}{C.END}
  3. SSH back in and verify:
               ssh -i {args.key} {args.user}@{args.host}

{C.YELLOW}Re-run with --verify-only to check system state without changes.{C.END}
""")


if __name__ == "__main__":
    main()
