# Prototype results

All runs happened in QEMU VMs (TCG, no KVM, 4 vCPU, 2 GiB RAM, OVMF) on a cloud build host, never on a real installation. Images were made from the official `haos_generic-x86-64-18.4.img` with `test-harness/build-test-image.sh`. Raw logs (serial consoles, per-scenario `results.md`) stayed on the build host. The excerpts below are copied from them.

**Test-only components, not representative of a Buildroot build:**

- `dm-crypt.ko`, `xts.ko` and `essiv.ko` were built out of tree against the release kernel config; the `=y` kernel fragment was not compiled.
- `clevis`, `jose`, `libjose`, `libjansson`, GNU `bash`, `libtinfo` and `resize2fs` were **copied from Ubuntu 24.04** into the rootfs. Their sizes below are measurements of those Ubuntu binaries, **not of Buildroot packages**.
- The data partition of the "already encrypted" images was converted offline by the harness. The `migrate` scenario is the one where HAOS itself converts a plain installation.
- The rootfs is recompressed with `mkfs.erofs -zlzma`, so boot timings are not comparable to the release image.
- The VM has no Internet access: Supervisor stays in `setup` (no Core install), which matters for the boot counter (see below).

## Summary

| # | Scenario | Result |
|---|---|---|
| 1 | Boot, HTTPS key available (`key-ok`) | **pass**: key fetched on attempt 1 about 20 s after boot, LUKS2 opened, `/mnt/data` mounted from `/dev/mapper/hassos-data`, persistent journal on it, Docker and Supervisor up, no ordering cycle |
| 2 | First version without generator overrides | **fail, by design of the test**: systemd broke ordering cycles by deleting `systemd-resolved`, `auditd` and the unlock job. Root cause: `systemd-journal-flush.service` has `RequiresMountsFor=/var/log/journal` |
| 3 | Tang reachable | **pass** (attempt 1) |
| 4 | Tang down at boot, started 3 min later | **pass**: retries, unlocked on attempt 7, boot continues by itself |
| 5 | Tang replaced by a server with other keys | **pass**: server answers 404 on `/rec/<kid>`, data stays locked |
| 6 | Tang keys rotated (`tangd-rotate-keys`) | **pass**: old keys kept hidden, existing `key.jwe` still works |
| 7 | 3 power cuts in a row while the key server is down | **problem**: `A_TRY` goes 1 → 2 → 3; the 4th boot (key server back) takes GRUB's **"Slot A (rescue shell)"** entry and stops in rescue mode (`sulogin`, "Press Enter for maintenance"). No console login within 15 min |
| 8 | Console prompt while waiting | **pass after a fix**: first the console went silent, because `systemd-ask-password-wall.service` stops the console agent. With the wall agent ordered after the unlock, "Data partition is waiting for its network key. Recovery passphrase:" is shown on the console during every locked boot |
| 9 | Recovery passphrase typed on the console | **pass after a fix**: with the key server answering 403, the prompt appears at 38 s; the passphrase is typed at 98 s, then "[INFO] Data partition unlocked with the recovery passphrase", console login at 136 s, Docker up. First attempt failed: `systemd-ask-password` ends the passphrase with a newline, and `--key-file=-` kept it, so the unlock now reads the passphrase without `--key-file` |
| 10 | Supervisor data disk view | **mismatch confirmed**: udisks2 `Device` = `/dev/dm-0`, os-agent `CurrentDevice` = `/dev/mapper/hassos-data`. Supervisor compares these, so a false "multiple data disks" issue is expected; it could not be read back because Supervisor stays in `setup` without Internet |
| 11 | Plain installation → in-place LUKS2 by HAOS (`migrate`) | **not completed; three bugs found and fixed, data never damaged**. Boot 1 (plain), as planned:
  - 20 000 canary lines and a 64 MiB random file written in `/mnt/data/supervisor/share`;
  - an SSH key and a Wi-Fi profile added on the overlay;
  - a full backup *failed* ("An error occurred while making backup": Supervisor stays in `setup` without Internet), but a partial backup of `share` succeeded (64 MB);
  - unlock configuration, `convert` marker and `haos.data-crypt=1` added.

  Then the in-place conversion by `haos-data-unlock` failed on three successive runs, each time **before** touching the data (partition still ext4, canary still readable):
  1. `resize2fs` is not in the image (the test copy from Ubuntu needed its own libraries: `undefined symbol: test_io_manager`);
  2. after that fix, `resize2fs` shrank the filesystem, then `cryptsetup reencrypt` failed with "Cannot create temporary header file", because it writes it in the current directory, `/` on the read-only erofs (fixed: run from `/run`);
  3. the last run failed again, and **its cause was not read before the end of the session**: the debug boot of that disk was its fourth boot without a slot marked good, so GRUB sent it to the rescue shell (see scenario 7).

  So **the power cut during conversion, the resume, the timing, the overlay/SSH/network checks after conversion and the backup restore were not tested** |
| 12 | `haos.wipe=1` on an encrypted system | First run: **failed safely**. `haos-wipe` runs before udev has created `/dev/disk/by-partlabel/hassos-data`, so it did not see LUKS2, stopped with "Data partition not found" and erased nothing, and both flags stayed in `cmdline.txt`. Fix: `udevadm settle` first. Re-test with the `udevadm settle` fix (last minutes of the session): **still fails**, "Failed to start Home Assistant OS Device Wipe Service", and the data mount then fails its dependency. The cause was not read before the session ended. Nothing was erased; this needs another look. |
| 13 | Release 18.4 untouched vs prototype rootfs without the flag | **pass**: same set of active units (apart from random per-container overlay mounts) and the same failed unit on both: `systemd-time-wait-sync`, because the VM has no NTP, so it also fails on the untouched release. Same milestone order: `mnt-overlay` → `mnt-data` → `sysinit` → `basic` → `network-online` → `docker` → `haos-supervisor` → `multi-user`. Only parallel bind mounts swap places between runs. Timestamps (s, monotonic): release 12.4 / 22.8 / 35.9 / 36.0 / 41.2 / 76.8 / 77.8 / 77.9; prototype rootfs 16.3 / 28.1 / 40.5 / 40.6 / 46.6 / 83.1 / 85.1 / 85.2, slower because of the all-lzma rootfs. `systemd-analyze` is not in the HAOS image, so these come from `ActiveEnterTimestampMonotonic` and the journal |
| 14 | `haos-expand` on the encrypted partition | **pass after fixes**. The first versions failed: no `PKNAME` for dm devices, lsblk listing the dm child first, then `cryptsetup resize` asking for a key (LUKS2 needs authorisation even with the volume key in the keyring). Final version grows the LUKS2 partition **before** the unlock, by partition label: partition 968 MB → 5.3 GB, mapping opened at full size, `systemd-growfs` takes ext4 to 5.2 GB, and `haos-swapfile` then creates its 1 GiB swap file. The unit ran 3 times in that boot (probably re-triggered by the udev change of the partition), which needs a look |
| 15 | Plaintext on the encrypted data partition | **pass** for the harness-converted image: 52 lines matching `hassio_supervisor\|containerd` in the original ext4, 0 in the LUKS2 partition |

Sizes, measured with **Ubuntu 24.04 binaries** (not a measure of Buildroot packages):

- `clevis` decrypt scripts, `jose`, `libjose`, `libjansson`: 322 860 bytes uncompressed;
- GNU `bash` and `libtinfo` (clevis does not run on busybox ash): 1 654 352 bytes;
- lzma erofs: about 200.4 MB without these, 201.3 MB with them plus `resize2fs` and its libraries.

The test rootfs also needed, for test purposes only:

- GNU bash for clevis;
- Ubuntu `resize2fs` with its own e2fsprogs libraries (the HAOS `libext2fs` lacks `test_io_manager`, and `resize2fs` is not in the image);
- out-of-tree `dm-crypt.ko`, `xts.ko` and `essiv.ko` (vermagic `6.18.58-haos SMP preempt mod_unload`).

## Details

### Ordering cycles without the generator overrides (first boot of the first version)

```
systemd[1]: sysinit.target: Found ordering cycle on systemd-resolved.service/start
systemd[1]: sysinit.target: Found dependency on systemd-tmpfiles-setup.service/start
systemd[1]: sysinit.target: Found dependency on systemd-journal-flush.service/start
systemd[1]: sysinit.target: Found dependency on var-log-journal.mount/start
systemd[1]: sysinit.target: Found dependency on mnt-data.mount/start
systemd[1]: sysinit.target: Found dependency on haos-data-unlock.service/start
systemd[1]: sysinit.target: Found dependency on network-online.target/start
...
systemd[1]: sysinit.target: Job systemd-resolved.service/start deleted to break ordering cycle
systemd[1]: sysinit.target: Job auditd.service/start deleted to break ordering cycle
systemd[1]: mnt-data.mount: Job haos-data-unlock.service/start deleted to break ordering cycle
```

### key-ok (HTTPS)

```
[   21.5] Starting HAOS data partition unlock (network key)...
[   22.9] haos-data-unlock[444]: [INFO] Data partition unlocked (attempt 1)
$ systemctl is-active haos-data-unlock mnt-data.mount var-lib-docker.mount containerd docker haos-supervisor
active (all)
$ findmnt /mnt/data; findmnt /var/log/journal
/mnt/data         /dev/mapper/hassos-data          ext4 rw,relatime,commit=30
/var/log/journal  /dev/mapper/hassos-data[/logs]   ext4
$ cryptsetup status hassos-data
  type: LUKS2  cipher: aes-xts-plain64  keysize: 512 bits  key location: keyring  device: /dev/vda8
$ journalctl -b | grep -i 'ordering cycle'
none
```

### locked-reboots (key server down, power cut about 30 s after the prompt, 3 times)

```
locked boot 1: slot A, rescue entry: no,  prompt shown; grubenv: A_OK=1 A_TRY=1 B_OK=0
locked boot 2: slot A, rescue entry: no,  prompt shown; grubenv: A_OK=1 A_TRY=2 B_OK=0
locked boot 3: slot A, rescue entry: no,  prompt shown; grubenv: A_OK=1 A_TRY=3 B_OK=0
boot 4 (key server up): GRUB "Slot A (rescue shell)" -> systemd.unit=recovery.target
  "You are in rescue mode ... Press Enter for maintenance (or press Control-D to continue)"
  no console login within 900 s
```

### Console while locked

Before the fix:

```
systemd-tty-ask-password-agent: Starting password query on /dev/ttyS0.
systemd[1]: Stopping Dispatch Password Requests to Console...
```

The cause is `systemd-ask-password-wall.service`: `ExecStartPre=-systemctl stop systemd-ask-password-console.path …`.

After the fix (wall agent ordered `After=haos-data-unlock.service`):

```
Data partition is waiting for its network key. Recovery passphrase: (press TAB for no echo)
```

### Tang

```
1. reachable:            [INFO] Key provider: tang / Data partition unlocked with the tang key (attempt 1)
2. down 3 min:           Error communicating with server http://10.0.2.2:8888 ... attempt 6 failed
                         [INFO] Data partition unlocked with the tang key (attempt 7)
3. other keys:           tangd: POST /rec/_sW6pE8F... => 404; data stays locked
4. rotated keys:         tangd-rotate-keys keeps .<old>.jwk; POST /rec/_sW6pE8F... => 200, unlocked (attempt 1)
```

### udisks2 / os-agent view of the data device

```
$ busctl get-property org.freedesktop.UDisks2 /org/freedesktop/UDisks2/block_devices/dm_2d0 org.freedesktop.UDisks2.Block Device
ay 10 47 100 101 118 47 100 109 45 48 0      # "/dev/dm-0"
$ busctl get-property io.hass.os /io/hass/os/DataDisk io.hass.os.DataDisk CurrentDevice
s "/dev/mapper/hassos-data"
$ ha resolution info
{"result":"error","message":"System is not ready with state: setup"}   # no Internet in the VM
```

### T5 comparison method

Both images booted with `console=ttyS0` added to `cmdline.txt` (nothing else changed on the release image). Active units: `systemctl list-units --all --state=active,failed`. Order: `journalctl -b -o short-monotonic` lines for "Mounted / Finished / Started / Reached target".
