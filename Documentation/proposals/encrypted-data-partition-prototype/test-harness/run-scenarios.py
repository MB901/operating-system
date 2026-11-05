#!/usr/bin/env python3
"""Boot scenarios for the encrypted data partition prototype (test only).

  run-scenarios.py <test.img> <keys-dir> <workdir> <scenario>...

Scenarios:
  key-ok      key server up from the start: data unlocked, mounted, Docker up
  key-late    key server down at boot, started after 4 minutes (longer than
              the 90 s default device timeout): boot must wait, then continue
  key-denied  server answers 403: data stays locked, retries continue; then
              the recovery passphrase typed on the console unblocks the boot
  control     image WITHOUT haos.data-crypt=1 and with a plain data partition
              (same rootfs): the boot must be the stock one

Results are printed and appended to <workdir>/results.md.
"""

import os
import subprocess
import sys
import time

from vm import VM, read_grubenv

HERE = os.path.dirname(os.path.abspath(__file__))
RECOVERY = os.environ.get("RECOVERY_PASSPHRASE", "recovery-passphrase-for-tests-only")

STATE = ("systemctl is-active haos-data-unlock.service mnt-data.mount var-lib-docker.mount "
         "var-log-journal.mount containerd.service docker.service haos-supervisor.service; true")
CHECKS = [
    ("unit states", STATE),
    ("failed units", "systemctl --failed --no-legend --plain"),
    ("ordering cycles", "journalctl -b --no-pager | grep -i -E 'ordering cycle|breaking ordering' || echo none"),
    ("unlock log", "journalctl -b -u haos-data-unlock --no-pager -o short-monotonic | tail -n 12"),
    ("expand log", "journalctl -b -u haos-expand --no-pager -o cat | tail -n 8"),
    ("block devices", "lsblk -o NAME,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS /dev/vda"),
    ("crypt status", "cryptsetup status hassos-data | head -n 8"),
    ("data mount", "findmnt /mnt/data; df -h /mnt/data | tail -n 1"),
    ("journal persistent", "findmnt /var/log/journal; ls /mnt/data/logs | head -n 3"),
    ("timing (monotonic, microseconds)", "for u in haos-data-unlock.service mnt-data.mount docker.service haos-supervisor.service; do "
     "echo \"$u $(systemctl show -P ActiveEnterTimestampMonotonic $u)\"; done"),
    ("swap", "swapon --show; free -m | head -n 3"),
    ("containers", "docker ps -a --format '{{.Names}} {{.Status}}' | head"),
    ("data disk as seen by udisks2 / os-agent",
     "busctl get-property org.freedesktop.UDisks2 /org/freedesktop/UDisks2/block_devices/dm_2d0 "
     "org.freedesktop.UDisks2.Block Device; busctl get-property io.hass.os /io/hass/os/DataDisk "
     "io.hass.os.DataDisk CurrentDevice"),
    ("supervisor data disk issues",
     "docker logs hassio_supervisor 2>&1 | grep -i -E 'data.?disk|multiple' | tail -n 8; "
     "docker exec hassio_cli ha resolution info --raw-json 2>/dev/null | head -c 1500; echo"),
    ("slot / boot counter", "cat /proc/cmdline | tr ' ' '\\n' | grep -E 'rauc.slot|systemd.unit'; "
     "grep -a -E '^(ORDER|A_OK|A_TRY|B_OK|B_TRY)=' /mnt/boot/EFI/BOOT/grubenv | tr '\\n' ' '; echo"),
]


class KeyServer:
    def __init__(self, keys: str, workdir: str, deny: bool = False):
        self.log = open(os.path.join(workdir, "key-server.log"), "a")
        args = [sys.executable, "-I", os.path.join(HERE, "key-server.py"), "--serve", keys]
        if deny:
            args.append("--deny")
        self.proc = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
        time.sleep(1)

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait()


def report(workdir: str, title: str, lines: list[str]) -> None:
    text = f"\n## {title}\n\n" + "\n".join(lines) + "\n"
    print(text, flush=True)
    with open(os.path.join(workdir, "results.md"), "a") as f:
        f.write(text)


def collect(vm: VM) -> list[str]:
    out = []
    for name, cmd in CHECKS:
        rc, text = vm.run(cmd)
        out.append(f"### {name}\n```\n$ {cmd}\n{text.strip()}\n```")
    return out


def scenario_key_ok(img, keys, workdir):
    srv = KeyServer(keys, workdir)
    vm = VM(img, workdir, "key-ok")
    try:
        t_login = vm.login()
        ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
        lines = [f"- console login after {t_login:.0f}s, data+docker active: **{ok}** (at {vm.elapsed():.0f}s)"]
        # give Supervisor time to start and run its resolution checks
        sup = vm.wait_cmd("docker logs hassio_supervisor 2>&1 | grep -q -i 'resolution'", 1200, 30)
        lines.append(f"- Supervisor ran its resolution checks: **{sup}** (at {vm.elapsed():.0f}s)")
        lines += collect(vm)
    finally:
        vm.stop()
        srv.stop()
    report(workdir, "Scenario key-ok", lines)


def scenario_key_late(img, keys, workdir):
    vm = VM(img, workdir, "key-late")
    srv = None
    try:
        # The console login only appears after Supervisor (serial-getty and
        # ha-cli are ordered After=haos-supervisor.service), i.e. after the
        # unlock. Watch the console instead while the key server is down.
        prompt = bool(vm.expect_opt(r"Recovery passphrase:", 600))
        t_prompt = vm.elapsed()
        login_seen = vm.seen(r"homeassistant login:", 240)
        lines = [f"- recovery passphrase prompt on the console: **{prompt}** (at {t_prompt:.0f}s)",
                 f"- console login prompt while locked (4 more minutes): **{login_seen}**"]
        srv = KeyServer(keys, workdir)
        t_srv = vm.elapsed()
        t_login = vm.login()
        ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
        lines += [f"- key server started at {t_srv:.0f}s, console login at {t_login:.0f}s, "
                  f"data+docker active: **{ok}** (at {vm.elapsed():.0f}s)"]
        lines += collect(vm)
    finally:
        vm.stop()
        if srv:
            srv.stop()
    report(workdir, "Scenario key-late", lines)


def scenario_key_denied(img, keys, workdir):
    srv = KeyServer(keys, workdir, deny=True)
    vm = VM(img, workdir, "key-denied")
    try:
        prompt = bool(vm.expect_opt(r"Recovery passphrase:", 600))
        lines = [f"- recovery passphrase prompt on the console: **{prompt}** (at {vm.elapsed():.0f}s)"]
        time.sleep(60)
        # Recovery: the passphrase is typed on the console (here by the harness)
        vm.send(RECOVERY)
        t_typed = vm.elapsed()
        t_login = vm.login()
        ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
        lines += [f"- passphrase typed at {t_typed:.0f}s, console login at {t_login:.0f}s, "
                  f"data+docker active: **{ok}** (at {vm.elapsed():.0f}s)"]
        lines += collect(vm)
    finally:
        vm.stop()
        srv.stop()
    report(workdir, "Scenario key-denied (+ recovery passphrase on the console)", lines)


def scenario_locked_reboots(img, keys, workdir):
    """Three boots in a row with the key server down (power cuts), then one with it up."""
    lines = []
    disk = os.path.join(workdir, "locked-reboots.qcow2")
    for n in (1, 2, 3):
        vm = VM(img, workdir, f"locked-boot{n}", disk_name="locked-reboots")
        m = vm.expect(r"rauc\.slot=(\S+)", 600)
        slot = m.group(1)
        unit = vm.seen(r"systemd\.unit=recovery\.target", 1)
        prompt = bool(vm.expect_opt(r"Recovery passphrase:", 600))
        time.sleep(30)
        vm.power_cut()
        lines.append(f"- locked boot {n}: kernel slot {slot}, rescue entry: {unit}, recovery prompt: {prompt}; "
                     f"grubenv after power cut: `{read_grubenv(disk, workdir)}`")
    srv = KeyServer(keys, workdir)
    vm = VM(img, workdir, "locked-boot4", disk_name="locked-reboots")
    try:
        m = vm.expect(r"rauc\.slot=(\S+)", 600)
        lines.append(f"- boot 4 with key server up: kernel command line slot {m.group(1)}, "
                     f"rescue entry: {vm.seen(r'systemd\.unit=recovery\.target', 1)}")
        try:
            t_login = vm.login(900)
            ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
            lines.append(f"- boot 4: console login at {t_login:.0f}s, data+docker active: **{ok}**")
            vm.wait_cmd("grep -q '^A_TRY=0' /mnt/boot/EFI/BOOT/grubenv", 900, 30)
            rc, env = vm.run("grep -a -E '^(ORDER|A_OK|A_TRY|B_OK|B_TRY)=' /mnt/boot/EFI/BOOT/grubenv | tr '\\n' ' '; "
                             "echo; rauc status 2>&1 | grep -E 'Booted from|Activated|boot status' ")
            lines.append(f"### boot 4 grubenv / rauc after waiting for Supervisor\n```\n{env.strip()}\n```")
            lines += collect(vm)
        except TimeoutError as err:
            lines.append(f"- boot 4: **no console login** ({err}); serial log in locked-boot4.serial.log")
    finally:
        vm.stop()
        srv.stop()
    report(workdir, "Scenario locked-reboots (3 power cuts while locked, then key back)", lines)


def scenario_control(img, keys, workdir):
    vm = VM(img, workdir, "control")
    try:
        t_login = vm.login()
        ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
        lines = [f"- console login after {t_login:.0f}s, data+docker active: **{ok}** (at {vm.elapsed():.0f}s)"]
        for name, cmd in [
            ("generator output", "ls -la /run/systemd/generator.early/ 2>&1 | head"),
            ("unlock unit", "systemctl status haos-data-unlock.service --no-pager 2>&1 | head -n 4"),
            ("data mount", "findmnt /mnt/data; findmnt /var/log/journal"),
            ("unit file in use", "systemctl show -P FragmentPath mnt-data.mount var-log-journal.mount"),
        ] + CHECKS[:3] + CHECKS[-2:]:
            rc, text = vm.run(cmd)
            lines.append(f"### {name}\n```\n$ {cmd}\n{text.strip()}\n```")
    finally:
        vm.stop()
    report(workdir, "Scenario control (no haos.data-crypt=1)", lines)


class TangServer:
    def __init__(self, keydir: str, workdir: str, port: int = 8888):
        self.log = open(os.path.join(workdir, "tang-server.log"), "a")
        self.proc = subprocess.Popen(["setsid", os.path.join(HERE, "tang-server.sh"), "serve", keydir, str(port)],
                                     stdout=self.log, stderr=subprocess.STDOUT)
        time.sleep(1)

    def stop(self) -> None:
        subprocess.run(["pkill", "-f", "TCP-LISTEN:8888"], check=False)
        self.proc.wait()


def tang_boot(img, workdir, name, server_dir, late=None, expect_ok=True):
    """Boot once with a Tang server (or none / a late one)."""
    srv = TangServer(server_dir, workdir) if server_dir and not late else None
    vm = VM(img, workdir, name)
    lines = []
    try:
        if late:
            prompt = bool(vm.expect_opt(r"Recovery passphrase:", 600))
            time.sleep(late)
            lines.append(f"- Tang down for {late}s after the prompt (prompt seen: {prompt})")
            srv = TangServer(server_dir, workdir)
        if expect_ok:
            t_login = vm.login()
            ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
            lines.append(f"- console login at {t_login:.0f}s, data+docker active: **{ok}**")
            rc, log = vm.run("journalctl -b -u haos-data-unlock --no-pager -o cat | tail -n 6")
            lines.append(f"```\n{log.strip()}\n```")
        else:
            prompt = bool(vm.expect_opt(r"Recovery passphrase:", 600))
            time.sleep(120)
            login_seen = vm.seen(r"homeassistant login:", 1)
            lines.append(f"- after 2 min: recovery prompt shown: {prompt}, data unlocked (console login seen): "
                         f"**{login_seen}** (expected False)")
    finally:
        if expect_ok:
            vm.stop()
        else:
            vm.power_cut()
        if srv:
            srv.stop()
    return lines


def scenario_tang(img, keys, workdir):
    """Tang provider: ok, late, foreign server, key rotation. keys = Tang key directory."""
    tsh = os.path.join(HERE, "tang-server.sh")
    lines = ["### 1. Tang reachable"] + tang_boot(img, workdir, "tang-ok", keys)
    lines += ["### 2. Tang down at boot, started 3 min later"] + tang_boot(img, workdir, "tang-late", keys, late=180)
    other = os.path.join(workdir, "tang-other")
    subprocess.run([tsh, "init", other], check=True)
    lines += ["### 3. Tang replaced by a server with other keys"] + tang_boot(img, workdir, "tang-other", other,
                                                                           expect_ok=False)
    rotated = os.path.join(workdir, "tang-rotated")
    subprocess.run(["cp", "-a", keys, rotated], check=True)
    subprocess.run([tsh, "rotate", rotated], check=True)
    files = sorted(os.listdir(rotated))
    lines += [f"### 4. Server keys rotated (key directory now: {files})",
              "Old keys are kept as hidden files, so the existing key.jwe must still work:"]
    lines += tang_boot(img, workdir, "tang-rotated", rotated)
    REPORT_TITLE = "Scenario tang"
    report(workdir, REPORT_TITLE, lines)


SCENARIOS = {"tang": scenario_tang, "control": scenario_control, "locked-reboots": scenario_locked_reboots, "key-ok": scenario_key_ok, "key-late": scenario_key_late, "key-denied": scenario_key_denied}

if __name__ == "__main__":
    img, keys, workdir = sys.argv[1:4]
    os.makedirs(workdir, exist_ok=True)
    for name in sys.argv[4:]:
        SCENARIOS[name](img, keys, workdir)
