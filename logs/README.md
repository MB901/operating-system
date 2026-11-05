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

## `repro/`: reproductions with a full `journalctl -b` (made after the session's deadline)

The `migrate` disk of `runs-mig5` and the `wipe` disk of `runs-7` were copied, and `A_TRY` was reset to 0 in their `grubenv` (otherwise GRUB takes the rescue entry). Each copy was then booted once with its `cmdline.txt` unchanged, so the failing step runs again. **These are new boots reproducing the state, not the original boots.** Each run has `*.units.txt` (unlock / wipe / expand / mount units), `*.state.txt` (cmdline, blkid, LUKS2 header, overlay config, failed units) and `*.journal.txt` (full `journalctl -b`).

- `migrate-repro`: the partition is LUKS2 with `Requirements: online-reencrypt-v2`. The conversion of boot 2 had started and was interrupted by the planned power cut after 16 MiB; the rest is still a plaintext `linear` segment. The original boot 3 did get the key (`runs-mig5/key-server.log`, four 200 responses at 07:02), so it is the resume (`cryptsetup reencrypt --resume-only`) that failed there. In this reproduction the key server on port 8444 was not reachable from the VM ("Failed to connect"), so the resume itself is not shown.
- `wipe-repro`: same failure as in `runs-7`, `haos-wipe: [ERROR] Data partition not found`, even with `udevadm settle`. The LUKS2 header is intact and nothing was erased. The cause is not established: LUKS detection (`blkid … /dev/disk/by-partlabel/hassos-data`) returned nothing at that point of the boot.

### `repro/r2/`: migrate resume with the key server reachable (cause found)

Same disk, booted again with the key server answering (`migrate-repro2.key-server.log`: 200 responses). The unlock script enters the resume path, and cryptsetup refuses:

```
[INFO] Resuming interrupted conversion of /dev/disk/by-partlabel/hassos-data
Device requires reencryption recovery. Run repair first.
[ERROR] Conversion failed, the data partition is left as it is
```

**Cause of the boot 3 failure:** after a power cut during `cryptsetup reencrypt --encrypt`, LUKS2 needs `cryptsetup repair` (with the key) before `cryptsetup reencrypt --resume-only`. The prototype skips the repair. The service is also started again and again by the units that need `/mnt/data` ("Start request repeated too quickly"). The fix (repair, then resume) is **not implemented or tested**. The data was not lost: 16 MiB encrypted, the rest still a plaintext linear segment, all of it described by the LUKS2 metadata.
