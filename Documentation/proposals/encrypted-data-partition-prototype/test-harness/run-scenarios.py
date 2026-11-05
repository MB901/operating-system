#!/usr/bin/env python3
"""Boot scenarios for the encrypted data partition prototype (test only).

  run-scenarios.py <test.img> <keys-dir> <workdir> <scenario>...

Scenarios:
  key-ok      key server up from the start: data unlocked, mounted, Docker up
  key-late    key server down at boot, started after 4 minutes (longer than
              the 90 s default device timeout): boot must wait, then continue
  key-denied  server answers 403: data stays locked, retries continue; then
              the recovery passphrase typed on the console unblocks the boot

Results are printed and appended to <workdir>/results.md.
"""

import os
import subprocess
import sys
import time

from vm import VM

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
        lines += collect(vm)
    finally:
        vm.stop()
        srv.stop()
    report(workdir, "Scenario key-ok", lines)


def scenario_key_late(img, keys, workdir):
    vm = VM(img, workdir, "key-late")
    srv = None
    try:
        t_login = vm.login()
        # keep the server down for 4 minutes after login
        time.sleep(240)
        rc, before = vm.run(STATE + "; systemctl --failed --no-legend --plain")
        lines = [f"- console login after {t_login:.0f}s (data still locked at that point)",
                 f"### state after 4 min without key server\n```\n{before.strip()}\n```"]
        srv = KeyServer(keys, workdir)
        t_srv = vm.elapsed()
        ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
        lines.insert(1, f"- key server started at {t_srv:.0f}s; data+docker active afterwards: **{ok}** (at {vm.elapsed():.0f}s)")
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
        t_login = vm.login()
        time.sleep(120)
        rc, locked = vm.run(STATE + "; ls /mnt/data | head -n 3; journalctl -b -u haos-data-unlock --no-pager -o cat | tail -n 4")
        lines = [f"- console login after {t_login:.0f}s",
                 f"### after 2 min with a revoked token\n```\n{locked.strip()}\n```"]
        # Recovery: passphrase typed on the console (here: piped by the harness)
        rc, rec = vm.run(f"printf '%s' '{RECOVERY}' | cryptsetup open --type luks2 --key-slot 1 "
                         "--key-file=- /dev/disk/by-partlabel/hassos-data hassos-data; echo open-rc=$?", 600)
        ok = vm.wait_cmd("systemctl is-active -q mnt-data.mount docker.service", 1200)
        lines += [f"### recovery passphrase\n```\n{rec.strip()}\n```",
                  f"- after recovery passphrase, data+docker active: **{ok}** (at {vm.elapsed():.0f}s)"]
        lines += collect(vm)
    finally:
        vm.stop()
        srv.stop()
    report(workdir, "Scenario key-denied (+ recovery passphrase)", lines)


SCENARIOS = {"key-ok": scenario_key_ok, "key-late": scenario_key_late, "key-denied": scenario_key_denied}

if __name__ == "__main__":
    img, keys, workdir = sys.argv[1:4]
    os.makedirs(workdir, exist_ok=True)
    for name in sys.argv[4:]:
        SCENARIOS[name](img, keys, workdir)
