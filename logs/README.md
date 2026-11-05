# Raw logs of the prototype runs (fork only)

Raw material behind `Documentation/proposals/encrypted-data-partition-prototype/RESULTS.md`.
All runs were done in QEMU VMs (TCG) on a cloud build host, from `haos_generic-x86-64-18.4.img`.

Redactions and exclusions:

- The bearer token of the test HTTPS key server was replaced by `<REDACTED-test-token…>` in `runs-mig4/` and `runs-mig5/migrate-boot1.serial.log`, where it was written to the overlay.
- Not included: test private keys (`server.key`, LUKS `net.key`, Tang key directories `tang-other/` and `tang-rotated/`), VM disks (`*.qcow2`) and the serial sockets.
- The recovery passphrase that appears is the harness default (`recovery-passphrase-for-tests-only`).

## Files

- `modules/`: `dm-crypt.ko`, `xts.ko` and `essiv.ko` with `SHA256SUMS`, the kernel configs, and `SOURCES.txt` (exact source URL and checksum).
- `runs/<run>/`, for each VM boot:
  - `*.serial.log`: the raw console, ANSI codes included. It contains the output of every command the harness ran, `journalctl` excerpts included;
  - `*.qemu.log`: QEMU stderr;
  - `results.md`: the per-scenario report. It is missing where the scenario was stopped before writing it;
  - `all.out` (harness stdout) and the key server logs.

| Run | Image | Content |
|---|---|---|
| `runs-b` | https3 | `locked-reboots` (3 power cuts while locked, 4th boot in rescue) and the first `key-denied` (passphrase newline bug) |
| `runs-b4` | https4 | `key-denied` with the fix, and the **first `wipe`** run (before `udevadm settle`) |
| `runs-7` | https7 | `key-ok` (haos-expand before unlock), and the **`wipe` re-run after `udevadm settle`** |
| `runs-ok5` | https5 | `key-ok` (`cryptsetup resize` asking for a key) |
| `runs-t` | tang3 | Tang scenarios 1–4 |
| `runs-final` | official / plain | T5 comparison, with the active unit lists and start order |
| `runs-mig4` | plain4 | `migrate`: boots 1–3, plus `migdbg` (debug boot: `resize2fs` OK, then "Cannot create temporary header file") |
| `runs-mig5` | plain5 | `migrate`: boots 1–3, plus `migdbg` (debug boot that fell into GRUB's rescue entry, 4th boot without a slot marked good) |

## What is missing

- **Full `journalctl -b` of the failing boots does not exist.** In encrypted mode the persistent journal is only bound to `/mnt/data/logs` after a successful unlock. The boots where the unlock or the wipe failed only had a volatile journal in `/run`, lost at power-off. What survives is in the serial logs: the console status lines, and the `journalctl -b -u haos-data-unlock` / `-u haos-wipe` output that the harness or `migdbg` printed there.
- The first `migrate` run (the `resize2fs: undefined symbol: test_io_manager` failure) has been deleted. Its unlock log is quoted in `RESULTS.md`.
- The first `key-ok` / `key-late` runs and the debug-shell run that found the `systemd-ask-password-wall` problem were deleted to free disk space. The relevant lines are quoted in `RESULTS.md`.
