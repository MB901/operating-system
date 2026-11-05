#!/usr/bin/env python3
"""Drive a HAOS test VM over its serial console (test fixture only).

Starts QEMU (TCG, OVMF) on a throw-away qcow2 overlay of the test image,
logs every byte of the serial console, logs in as root on the console and
runs shell commands. Used by run-scenarios.py.
"""

import os
import re
import socket
import subprocess
import time


class VM:
    def __init__(self, base_image: str, workdir: str, name: str, mem: str = "2048", smp: str = "4"):
        self.workdir = workdir
        self.name = name
        self.disk = os.path.join(workdir, f"{name}.qcow2")
        self.sock = os.path.join(workdir, f"{name}.serial")
        self.log_path = os.path.join(workdir, f"{name}.serial.log")
        self.buf = ""
        self.pos = 0
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-b", os.path.abspath(base_image),
                        "-F", "raw", self.disk], check=True)
        if os.path.exists(self.sock):
            os.unlink(self.sock)
        self.proc = subprocess.Popen([
            "qemu-system-x86_64", "-machine", "q35", "-accel", "tcg,thread=multi", "-cpu", "max",
            "-smp", smp, "-m", mem, "-bios", "/usr/share/ovmf/OVMF.fd",
            "-drive", f"file={self.disk},format=qcow2,if=virtio",
            "-nic", "user,model=virtio-net-pci",
            "-serial", f"unix:{self.sock},server=on,wait=on",
            "-display", "none", "-monitor", "none",
        ], stdout=subprocess.DEVNULL, stderr=open(os.path.join(workdir, f"{name}.qemu.log"), "w"))
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.1)
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(self.sock)
        self.s.settimeout(1)
        self.log = open(self.log_path, "w", errors="replace")
        self.t0 = time.time()

    def elapsed(self) -> float:
        return time.time() - self.t0

    def _read(self) -> None:
        try:
            data = self.s.recv(65536)
        except socket.timeout:
            return
        if data:
            text = data.decode(errors="replace")
            self.buf += text
            self.log.write(text)
            self.log.flush()

    def expect(self, pattern: str, timeout: float) -> re.Match:
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            m = rx.search(self.buf, self.pos)
            if m:
                self.pos = m.end()
                return m
            self._read()
        raise TimeoutError(f"{self.name}: '{pattern}' not seen within {timeout}s")

    def send(self, line: str) -> None:
        self.s.sendall(line.encode() + b"\n")

    def login(self, timeout: float = 1200) -> float:
        self.expect(r"homeassistant login: ", timeout)
        t = self.elapsed()
        self.send("root")
        self.expect(r"# $|# ", 120)
        # quiet kernel/journal messages on the console while running commands
        self.run("dmesg -n 1; stty cols 200")
        return t

    def run(self, cmd: str, timeout: float = 300) -> tuple[int, str]:
        marker = f"@@{int(time.time() * 1000)}@@"
        self.send(f"echo {marker}B; {cmd}; echo {marker}E $?")
        self.expect(re.escape(marker) + "B\r?\n", timeout)
        start = self.pos
        m = self.expect(re.escape(marker) + r"E (\d+)", timeout)
        out = self.buf[start:m.start()]
        return int(m.group(1)), out.replace("\r", "")

    def wait_cmd(self, cmd: str, timeout: float, interval: float = 10) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            rc, _ = self.run(cmd)
            if rc == 0:
                return True
            time.sleep(interval)
        return False

    def stop(self) -> None:
        try:
            self.send("poweroff")
            self.proc.wait(timeout=180)
        except Exception:
            self.proc.kill()
        self.log.close()
