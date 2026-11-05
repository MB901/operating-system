# Proposal: optional encryption of the data partition with an off-machine key (generic-x86-64)

Status: **draft for discussion**. Context: [discussion #1567](https://github.com/orgs/home-assistant/discussions/1567).
A throw-away prototype exists on the branch `prototype/encrypted-data-network-key` of this fork. It was
tested only in a QEMU VM built from the 18.4 release image, without a Buildroot build. See
[`encrypted-data-partition-prototype/`](encrypted-data-partition-prototype/) and its `RESULTS.md`.
It is meant to answer questions, not to be merged.

The goal of this document is to give maintainers something concrete to accept,
reject or redirect before anyone writes production code. Statements are tagged:

- **[V]** verified by reading the code (file paths given), at `home-assistant/operating-system` commit `3d192e5` (dev, 2026-11-04), unless stated otherwise;
- **[T]** observed in the prototype VM (18.4 release image plus the prototype files), see `RESULTS.md`;
- **[H]** hypothesis, not verified.

## 1. Need

Many users run HAOS on a small x86 PC next to other sensitive services
(documents, password manager). A common worry is theft of the **whole
machine**, not only the SSD. Today the data partition is plain ext4 [V]
(`buildroot-external/genimage/partitions-os-gpt.cfg`, `package/hassio/create-data-partition.sh`).

Constraints that make the usual answers unsuitable for this audience:

- **No passphrase at boot**: the machine reboots by itself after a power cut, often without a keyboard or screen.
- **TPM-only sealing does not help** against theft of the whole machine, since the TPM travels with the disk.
- **A VM / another OS is out of scope**: the user wants to keep HAOS.

## 2. Threat model

In scope:

- An attacker steals the whole device (or the SSD) and has unlimited offline time. They can power it on at another location, or read the disk elsewhere.
- Goal: the contents of `hassos-data` stay unreadable. That covers Docker images and volumes, Supervisor and app data, backups, `/mnt/data/logs` (persistent journal) and the swap file.

Out of scope (state it loudly in user docs):

- **An attacker who can reach the key server.** The overlay stays in clear (section 8), so the thief gets the home **Wi-Fi password** and the key server address. Someone who steals the box and comes back within Wi-Fi range can fetch the key. Mitigations are on the server side: wired-only access to the key server, alerting on key requests, manual approval or revocation after a theft. This is the main limit of the design and must be in the user docs.
- Evil-maid or tampering of the unencrypted boot/system partitions. There is no Secure Boot or dm-verity enforcement on the root today [H]: `CONFIG_DM_VERITY=y` is in the kernel fragment, but nothing in the files read uses it.
- Memory attacks on a running machine, cold boot, DMA.

## 3. What the code looks like today

All [V] unless noted.

**Partitions.** GPT: `hassos-boot`, `hassos-kernel0/1`, `hassos-system0/1`, `hassos-bootstate`, `hassos-overlay`, `hassos-data` (`genimage/partitions-os-gpt.cfg`). `hassos-data` is the last partition and takes the remaining space.

**Boot.** GRUB loads `bzImage` from the kernel slot with `root=PARTUUID=… rootfstype=erofs` (`board/pc/grub.cfg`). **No initramfs** is used on generic-x86-64. GRUB counts boot attempts per slot (`A_TRY`/`B_TRY` in `grubenv`, `board/pc/grub.cfg`). After three attempts it falls back to the other slot, or to the rescue entries (`systemd.unit=recovery.target`). Only Supervisor resets the counter, by marking the slot good through RAUC (`supervisor/os/manager.py:475` in `home-assistant/supervisor`).

**Data partition lifecycle (`rootfs-overlay/usr/lib/systemd/system/`).**

- `mnt-data.mount` (label `hassos-data`, `WantedBy=local-fs.target`, after `haos-expand.service`).
- `haos-expand` (grows the partition with `sfdisk`), then `systemd-growfs@mnt-data` (`Before=local-fs.target`).
- `haos-data.service`: data disk move, `e2image -ra`, then relabel.
- `haos-data-disk-detach.service`: first boot, relabels data partitions not on the boot disk.
- `haos-wipe.service`: `haos.wipe=1`.

Consumers of `/mnt/data` and their ordering:

- **Before `sysinit.target`**:
  - `var-log-journal.mount`, `var-lib-docker.mount` (wanted by `haos-bind.target`, which is `Before=sysinit.target`);
  - `mnt-data-swapfile.swap` (in `swap.target`);
  - `systemd-journal-flush.service`, which has `RequiresMountsFor=/var/log/journal` (upstream systemd unit, [T]).
- **After `basic.target`**:
  - `RequiresMountsFor=/mnt/data`: `docker-prepare`, `docker` (`docker.service.d/haos.conf`), `haos-docker-reset`, `haos-apparmor`, `raucdb-update`, `haos-supervisor`;
  - `containerd` keeps its state in `/mnt/data/docker/containerd` (`etc/containerd/config.toml`) but has **no mount dependency**. Today it simply relies on `/mnt/data` being mounted early.
  - `etc/tmpfiles.d/data.conf` creates `/mnt/data/supervisor` during sysinit.

**Overlay (`hassos-overlay`, `/mnt/overlay`).** Bind-mounted into `/etc` and `/root` by units wanted by `haos-bind.target`:

- NetworkManager `system-connections` (**Wi-Fi PSKs**);
- `/etc/dropbear` (SSH **host keys**) and `/root/.ssh` (**authorized_keys**);
- `/root/.docker` (**registry credentials**, if any);
- Bluetooth pairings (`/var/lib/bluetooth`) and `/var/lib/systemd`;
- hostname, timesyncd, udev rules.

None of this needs `/mnt/data`. Core dumps are not stored (`etc/systemd/coredump.conf`: `Storage=none`).

**Network and consoles.** NetworkManager only needs the overlay binds (`NetworkManager.service.d`). The network is **not** up when `mnt-data.mount` runs today. Both consoles are ordered after Supervisor: `serial-getty@.service.d/haos.conf` and `ha-cli@.service` have `After=haos-supervisor.service`. So **no login prompt appears until `/mnt/data` is mounted** [V, T].

**Updates.** RAUC slots are `boot`, `kernel.0/1` and `rootfs.0/1` (`ota/system.conf.gtpl`). Neither data nor overlay is a RAUC slot. `ota/rauc-hook` preserves `cmdline.txt` and `grubenv` when updating the boot slot.

**Moving the data disk.** Supervisor (`supervisor/os/data_disk.py`) formats the target with udisks2, os-agent writes `/mnt/overlay/move-data` (`datadisk/datadisk.go`), and `haos-data` copies on the next boot. Supervisor and os-agent find the data disk through the **filesystem label** `hassos-data`, and os-agent reports `CurrentDevice` from the mount source of `/mnt/data`.

**Crypto tooling in the image.**

- `cryptsetup` is built in through `udisks2` → `libblockdev` crypto plugin → `cryptsetup` (`package/udisks2/Config.in`, Buildroot `package/libblockdev/Config.in`). Present in the 18.4 rootfs as `/usr/sbin/cryptsetup` [V, T].
- `systemd` is built with libcryptsetup: `/usr/lib/systemd/systemd-cryptsetup` and its generator are in the 18.4 rootfs [V]. The prototype does not use them.
- `curl` is present. **`/bin/bash` is busybox ash** (`busybox.config`: `CONFIG_BASH_IS_ASH=y`), not GNU bash. `clevis` is written for GNU bash and fails with it [T]. `jose` and `luksmeta` exist as Buildroot packages, **`clevis` and `tang` do not**.
- **`resize2fs` and `wipefs` are not in the image** (e2fsprogs is built without resize2fs; only `systemd-growfs` can grow). An in-place conversion needs to shrink ext4, so it needs `BR2_PACKAGE_E2FSPROGS_RESIZE2FS` [V, T].
- libcurl is built with `--with-ca-path=/etc/ssl/certs` (Buildroot `package/libcurl/libcurl.mk`). `--cacert` alone therefore does not restrict the trusted CAs.
- **The kernel has no `DM_CRYPT`, `CRYPTO_XTS` or `CRYPTO_AES_NI_INTEL`.** I checked the `IKCONFIG` of the 18.4 release kernel `6.18.58-haos`, the fragments and upstream `x86_64_defconfig`. `MODVERSIONS` and module signing are off, which is what let the prototype load out-of-tree modules.

## 4. Proposed solution (generic-x86-64 only)

Opt-in. Default images and existing installs are unchanged. In the prototype the switch is `haos.data-crypt=1` in `cmdline.txt`; without it nothing changes [T, control scenario].

1. **Kernel**: `CONFIG_DM_CRYPT=y`, `CONFIG_CRYPTO_XTS=y`, `CONFIG_CRYPTO_AES_NI_INTEL=y` in `board/pc/generic-x86-64/kernel.config`. Merged with the other fragments through `x86_64_defconfig` + `olddefconfig`, they come out `=y`, and `scripts/check-dotconfig.py` reports nothing. The kernel itself **was not built**: the VM used the release kernel with the same options built as modules.
2. **Format**: `hassos-data` becomes a LUKS2 container (aes-xts-plain64). Keyslot 0 holds the network key (random, 512 bits, cheap PBKDF since it has full entropy). Keyslot 1 holds a recovery passphrase (argon2id). Unlocking with `--key-slot 0` avoids paying argon2id on every boot. The ext4 label `hassos-data` is inside the mapping (`/dev/mapper/hassos-data`).
3. **Late unlock, no initramfs.** `haos-data-unlock.service` runs `After=network-online.target`. It gets the key from a provider (section 5) and pipes it into `cryptsetup open --key-file=-`, so the key never touches disk.
   A systemd generator (`haos-data-crypt-generator`, active only with the flag) writes replacement units into the "early" generator directory. These replacements move `/mnt/data` and its consumers out of `local-fs.target`/`sysinit.target`. Without them the boot has ordering cycles [T]: the first prototype boot deleted `systemd-resolved`, `auditd` and the unlock job itself to break them. What the generator does:
   - `mnt-data.mount`: from `/dev/mapper/hassos-data`, `Requires/After=haos-data-unlock.service`, `DefaultDependencies=no`.
   - `JobRunningTimeoutSec=infinity` on the mapper and label device units. Otherwise the default 90 s device timeout fails the mount for good when the key server is late.
   - Replacements without `Before=local-fs/sysinit/swap.target` for `systemd-growfs@mnt-data`, `var-lib-docker.mount` and `mnt-data-swapfile.swap`.
   - `var-log-journal.mount` is **masked**: any mount unit at `/var/log/journal` is required by `systemd-journal-flush.service` during sysinit. `haos-data-crypt-post.service` does the bind, `journalctl --relinquish-var` and `--flush` after unlock, and undoes the bind at shutdown. It also re-runs `tmpfiles.d/data.conf`.
   - A drop-in giving `containerd.service` `RequiresMountsFor=/mnt/data`.
   - `haos-data.service` (move), `haos-data-disk-detach.service` and `haos-wipe.service` are masked, because they are unsafe with LUKS (section 9).
   - `haos-expand` finds the parent partition of the dm device through sysfs, grows it, then runs `cryptsetup resize`. `lsblk` gives no `PKNAME` for dm devices, and `/dev/mapper/*` is a device node, not a symlink, in HAOS [T].
4. **Alternative: initramfs with network.** It is cleaner for ordering (nothing in the main system changes), but it adds a boot stage and an artifact to keep in sync through RAUC, and it duplicates NetworkManager configuration (Wi-Fi, VLAN, static IP) in early boot. The amount of replacement units above is the real price of the late-unlock approach, and it is a maintenance question (section 10).

## 5. Where the key comes from

The unlock script takes "a command that prints the key on stdout". Two providers are prototyped. HTTPS is used when `key-url` + `ca.pem` + `token` are on the overlay. Tang is used when `key.jwe` is there. HTTPS keeps working when Tang support is present [T].

**HTTPS** [T]: a GET with a bearer token.

- Only the CA in `ca.pem` is accepted (`--cacert` plus an empty `--capath`, because of the built-in CA path).
- `curl -q --proto =https --noproxy '*' --max-filesize`; the token is passed through `--config -`, so it never appears on the command line.

**Tang** [T]: `clevis decrypt < key.jwe | cryptsetup open --key-file=- …`.

- **No LUKS token or cryptsetup plugin is needed to start.** `key.jwe` is the LUKS key encrypted with `clevis encrypt tang`, created with the server's advertisement passed as a file, so nothing has to be confirmed by hand.
- A later step could use `clevis luks bind` (LUKS2 token in the header) or the systemd-cryptsetup clevis token plugin. That is not needed for a first version.
- Size, **measured with Ubuntu 24.04 binaries copied into the test rootfs, not Buildroot packages**:
  - clevis decrypt scripts plus `jose`, `libjose` and `libjansson`: 323 kB uncompressed;
  - GNU `bash` + `libtinfo`, needed by clevis because `/bin/bash` is busybox: 1.65 MB uncompressed;
  - the whole test addition (these plus `resize2fs`) grows the lzma erofs by about 0.9 MB.

  `curl`, OpenSSL and zlib are already present.

Comparison. **This is a choice for maintainers, not a recommendation.**

| | HTTPS (custom) | Tang (clevis) |
|---|---|---|
| New packages in the image | none (`curl` present) | `clevis` (new Buildroot package), `jose` (exists), `jansson`, and **GNU `bash`** (clevis does not run on busybox ash) |
| What a stolen box carries | URL, CA, **bearer token** (enough to ask for the key) | `key.jwe` and the server URL (enough to ask the server to help decrypt) |
| What the server stores | the LUKS key itself | only its own key pair; it never sees the LUKS key |
| Server software | anything that can serve a file with auth (NAS, reverse proxy, small script) | `tangd` (packaged in most distros, small) |
| Transport security | TLS with a pinned CA | plain HTTP is fine by design (McCallum-Relyea exchange); a fake server with other keys cannot help [T] |
| Revocation after a theft | delete or change the token or key on the server | remove the server keys; old JWEs become useless |
| Key rotation | replace the key file and the LUKS keyslot | `tangd-rotate-keys` keeps old keys hidden, so existing JWEs keep working [T]; re-encrypt the JWE later |
| Several servers / threshold | custom work | `sss` pin (e.g. 1 of 2 Tang servers) for free |
| Standard / known in the Linux world | ad hoc | yes (RHEL NBDE, Fedora, Debian) |

## 6. When the key is unreachable

- Retry forever with backoff, 5 s to 60 s [T]. A power cut often brings the PC back **before** the router or NAS. Nothing ever wipes or reformats.
- Everything that needs `/mnt/data` waits, including Supervisor and both consoles (section 3). The console shows systemd's "A start job is running … (no limit)".
- The unlock script asks for the recovery passphrase on the console through the systemd password agent (`systemd-ask-password`, while the network attempts continue) [T]. The prompt is just there, so a keyboard is never required. Whoever succeeds first wins, and the prompt disappears.
  - Pitfall found in the VM: upstream `systemd-ask-password-wall.service` runs `systemctl stop systemd-ask-password-console.path …` as soon as user sessions are allowed, because systemd assumes a getty is up by then. On HAOS the gettys wait for Supervisor, so the prompt vanished and the console went silent [T]. The generator orders the wall agent after the unlock.
- **Boot counting, the main operational risk found**: while locked, Supervisor never marks the slot good, so GRUB's `A_TRY` grows on every boot. In the VM, three power cuts while the key server was down gave `A_TRY` 1 → 2 → 3. The fourth boot (key server back) took **"Slot A (rescue shell)"** and stopped at `sulogin` ("Press Enter for maintenance") [T]. On a fresh install `B_OK=0`, so GRUB has nothing to fall back to.
  - For a headless box, a few power cuts while the router is down would leave it stuck until someone comes with a keyboard.
  - In this offline VM even a successful boot leaves `A_TRY=1`, because Supervisor stays in `setup`. On a real install Supervisor marks good boots and resets the counter, but a locked boot never does.
  - This is an open question (section 10).

## 7. Recovery and backup of the key

- Recovery passphrase in keyslot 1, generated at setup and shown once. It can be typed on the console while waiting [T].
- Header backup (`cryptsetup luksHeaderBackup`): a damaged header makes the data unrecoverable.
- Procedure from a live system to open the volume by hand and copy data out.
- Key rotation and revocation (`luksChangeKey`, `luksKillSlot`) without reformatting.

## 8. What stays in clear

- `hassos-boot` (GRUB, `grubenv`, `cmdline.txt` with the flag), kernel slots, `hassos-system0/1`, `hassos-bootstate`.
- **`hassos-overlay`**: Wi-Fi PSK and other NetworkManager secrets, SSH host keys and `authorized_keys`, Bluetooth pairing keys, `/root/.docker` credentials, hostname, and the unlock configuration (URL, CA, token or `key.jwe`). See section 2 for what this means. Encrypting the overlay as well would need the network *before* the overlay, i.e. an initramfs.
- LUKS2 header metadata and the partition layout.
- With `allow-discards` (not enabled in the prototype), a coarse map of used blocks.

## 9. Migration and the existing data disk features

- **New installs**: create LUKS2 + ext4 at first boot, or with a dedicated "encrypt" action. Provisioning (enrolling the key, showing the recovery passphrase) is **not prototyped**: the test image is converted offline on the build host.
- **Existing installs**, options:
  - **A. Backup / restore** into a new LUKS partition. Simplest to explain, needs downtime and a backup that fits.
  - **B. In-place** `cryptsetup reencrypt --encrypt --reduce-device-size` after shrinking ext4. No extra disk, but long. The release data ext4 is already at its minimum size, so `resize2fs` refused to shrink it in the test build [T]. This path needs free space at the end of the partition.
- **Data disk move** (`haos-data`, `e2image -ra`) would copy the **decrypted** filesystem to an unencrypted external disk, then relabel. Disabled by the prototype. It needs a LUKS-aware path in OS, os-agent and Supervisor.
- **Disk detach** (`haos-data-disk-detach`) cannot find the disk of a dm device and would relabel the internal data filesystem as disabled. Disabled by the prototype.
- **Wipe** (`haos.wipe=1`) looks for the label before unlock. Disabled by the prototype. It needs to decide whether to recreate LUKS2 or go back to plain ext4.
- **Supervisor data disk view**: on D-Bus, udisks2 reports the mapping's `Device` as `/dev/dm-0`, while os-agent's `CurrentDevice` is the mount source `/dev/mapper/hassos-data` [T]. Supervisor compares these strings in `resolution/checks/multiple_data_disks.py` (and in `os/data_disk.py` and `mounts/disks.py`), so it would see the current data disk as a *second* disk with the `hassos-data` label. That is a false "multiple data disks" issue, and the device is not protected from being offered as a mount [H]. In the VM Supervisor stays in `setup` (no Internet), so the issue itself could not be read back. Fix: os-agent should report the resolved device, or Supervisor should compare device numbers.
- **Downgrade**: a slot without dm-crypt or the generator cannot open the data. RAUC slot B is the previous OS, so encryption should only be enabled once both slots have a capable release.

## 10. Open questions for maintainers

1. Is an opt-in encrypted data partition acceptable in principle for generic-x86-64? Any objection to `CONFIG_DM_CRYPT` (+ XTS, AES-NI) in its kernel?
2. Late unlock in the main system (generator, section 4.3) versus an initramfs: which is acceptable to maintain? The generator replaces or masks about ten units.
3. Key source: HTTPS, Tang, both, or a generic "key command" hook (section 5)?
4. **Boot counting while locked** (observed: rescue shell after three locked boots): should waiting for the key count as a failed boot? Options:
   - keep GRUB's behaviour (rescue/fallback), and document it;
   - mark the slot good once the unlock succeeds;
   - reset the try counter while the unlock service is only waiting for the network key, which is not a slot failure. Distinguishing that from an update that broke the network is the hard part.
5. Consoles are ordered after Supervisor. Is a recovery prompt through the systemd password agent acceptable, or should `ha-cli` show a "data locked" state?
6. Is it acceptable that overlay secrets (Wi-Fi PSK, SSH keys, unlock config) stay in clear in a first version, given section 2?
7. Data disk move, wipe and detach with LUKS: implement, or refuse while encrypted? Which side owns it (OS, os-agent, Supervisor)?
8. Provisioning and migration: first-boot encryption only, or an in-place path for existing installs?
9. Where should the switch live: `cmdline.txt` flag (survives RAUC updates through `rauc-hook`), overlay, or a Supervisor/OS-agent API?
10. TRIM (`--allow-discards`): enable for SSD health, or not?
11. Should this go through Architecture Discussions first?

## 11. Cost of reproducing

- **The prototype approach** (no Buildroot build) is what produced the [T] results:
  - extract the release rootfs and kernel config;
  - build only `dm-crypt.ko`, `xts.ko` and `essiv.ko` against the matching kernel source (seconds after `modules_prepare`);
  - rebuild the erofs (about 5 min, single-threaded lzma);
  - convert the data partition offline.

  It runs in a VM without KVM (TCG), and the boot reaches Docker in about a minute.
- **A full HAOS Buildroot build** (needed to test the `=y` kernel fragment or real packages) is [H]: several hours from scratch on 4 cores and tens of GB of disk. Under WSL on a 12 GB PC, the WSL memory limit would have to be raised. Not attempted.
