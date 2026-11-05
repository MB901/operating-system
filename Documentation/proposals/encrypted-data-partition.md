# Proposal: optional encryption of the data partition with an off-machine key (generic-x86-64)

Status: **draft for discussion**, no code. Context: [discussion #1567](https://github.com/orgs/home-assistant/discussions/1567).

The goal of this document is to give maintainers something concrete to accept,
reject or redirect before anyone writes code. Statements are tagged:

- **[V]** verified by reading the code (file paths given), at `home-assistant/operating-system` commit `3d192e5` (dev, 2026-11-04) unless stated otherwise;
- **[H]** hypothesis, not verified, needs a build or a maintainer's answer.

## 1. Need

Many users run HAOS on a small x86 PC next to other sensitive services
(documents, password manager). A common worry is theft of the **whole
machine**, not only the SSD. Today the data partition is plain ext4 [V]
(`buildroot-external/genimage/partitions-os-gpt.cfg`, `package/hassio/create-data-partition.sh`).

Constraints that make usual answers unsuitable for this audience:

- **No passphrase at boot**: the machine reboots by itself after a power cut, often without a keyboard or screen.
- **TPM-only sealing does not help** against theft of the whole machine, since the TPM travels with the disk.
- **A VM / other OS is out of scope**: the user wants to keep HAOS.

## 2. Threat model

In scope:

- An attacker steals the whole device (or the SSD) and has unlimited offline time. They can power it on at another location, or read the disk elsewhere.
- Goal: the contents of `hassos-data` (Docker images and volumes, Supervisor data, add-on data, backups, `/mnt/data/logs`, swap file) stay unreadable.

Out of scope (state it loudly in user docs):

- Attacker with network access to the key server *while it still serves the key* (the owner must be able to revoke the key/credential quickly after a theft).
- Evil-maid or tampering of unencrypted boot/system partitions (no Secure Boot or dm-verity enforcement on the root today [H]; `CONFIG_DM_VERITY=y` is in the kernel fragment but nothing in the files read uses it).
- Memory attacks on a running machine, cold-boot, DMA.
- Secrets that remain in clear (see section 8).

## 3. What the code looks like today

All [V] unless noted.

**Partitions.** GPT: `hassos-boot`, `hassos-kernel0/1`, `hassos-system0/1`, `hassos-bootstate`, `hassos-overlay`, `hassos-data` (`genimage/partitions-os-gpt.cfg`). `hassos-data` is the last partition and takes the remaining space.

**Boot.** GRUB loads `bzImage` from the kernel slot with `root=PARTUUID=… rootfstype=erofs` (`board/pc/grub.cfg`). **No initramfs** is used on generic-x86-64: the root is mounted directly by the kernel, the command line has no `initrd`, and the defconfig has no cpio/initramfs target (`configs/generic_x86_64_defconfig`). Only the rpi5 `config.txt` mentions `auto_initramfs`.

**Data partition lifecycle (systemd, `rootfs-overlay/usr/lib/systemd/system/`).**

- `mnt-data.mount`: `What=/dev/disk/by-label/hassos-data`, `Type=ext4`, `WantedBy=local-fs.target`, ordered after `haos-expand.service` and its fsck unit.
- `haos-expand.service` → `/usr/libexec/haos-expand`: finds the device with `findfs LABEL=hassos-data`, relocates the GPT backup header and grows the partition with `sfdisk`; then `systemd-growfs@mnt-data` grows the ext4 after mount.
- `haos-data.service` (only if `/mnt/overlay/move-data` exists) → `/usr/libexec/haos-data`: copies the old partition to `hassos-data-external` with `e2image -ra`, then renames the old label to `hassos-data-old`.
- `haos-data-disk-detach.service` (first boot): scans `blkid LABEL=hassos-data` and relabels any data partition not on the root disk to `hassos-data-dis`.
- `haos-wipe.service` (`haos.wipe=1` on the command line): `mkfs.ext4 -L hassos-data` on the label.
- Consumers of `/mnt/data`: `var-log-journal.mount` (persistent journal, **`WantedBy=haos-bind.target`, which is `Before=sysinit.target`**), `var-lib-docker.mount`, `docker-prepare.service`, `haos-swapfile.service`/`mnt-data-swapfile.swap`, `haos-supervisor.service` (`RequiresMountsFor=/mnt/data /mnt/boot /mnt/overlay`), `raucdb-update.service`.

**Overlay (`hassos-overlay`, ext4, `/mnt/overlay`).** Bind-mounted into `/etc` and `/root` by `*.mount` units wanted by `haos-bind.target`: NetworkManager `system-connections` (**Wi-Fi PSKs and other connection secrets**), `/etc/dropbear` (SSH **host keys**), `/root/.ssh` (**authorized_keys**), hostname/hosts, timesyncd, udev rules, `/var/lib/bluetooth` (pairings), `/var/lib/systemd`, `/root/.docker`. None of this needs `/mnt/data`.

**Network availability.** NetworkManager only needs the overlay bind mounts (`NetworkManager.service.d` → `RequiresMountsFor=/etc/hostname /etc/hosts /etc/NetworkManager/system-connections`). It starts after `local-fs.target`/`sysinit.target`; **the network is not up when `mnt-data.mount` runs today** (it is part of `local-fs.target`). Supervisor waits for `network-online.target` (`haos-supervisor.service`).

**Updates.** RAUC slots are `boot` (vfat), `kernel.0/1` (raw) and `rootfs.0/1` (raw), all by `/dev/disk/by-partlabel/hassos-*` (`ota/system.conf.gtpl`). Neither data nor overlay is a RAUC slot, so an OS update does not touch the data partition. The boot slot is updated by `ota/rauc-hook`, which preserves `cmdline.txt` and `grubenv`.

**Moving the data disk.** Supervisor `supervisor/os/data_disk.py` (`migrate_disk`) formats the target with udisks2 (GPT, one partition named `hassos-data-external`), asks `os-agent` to create `/mnt/overlay/move-data` (`datadisk/datadisk.go`), then reboots; `haos-data.service` does the block copy. Supervisor and os-agent identify the data disk through the **filesystem label** `hassos-data` (`os/const.py`, `GetRootDeviceFromLabel("hassos-data")`).

**Crypto tooling in the image.**

- `udisks2` selects `BR2_PACKAGE_LIBBLOCKDEV_CRYPTO`, which selects `BR2_PACKAGE_CRYPTSETUP` (`buildroot-external/package/udisks2/Config.in`, `package/libblockdev/Config.in` in the HA Buildroot fork, branch `2024.02.x-haos`). `BR2_PACKAGE_UDISKS2=y` is in the x86-64 defconfig, so **`cryptsetup` (with libargon2, json-c, openssl) is already built into the image** [V by Kconfig; not checked in a built image].
- `systemd.mk` passes `-Dlibcryptsetup=true` when `BR2_PACKAGE_CRYPTSETUP=y`, so `systemd-cryptsetup` is probably present [H: not checked in a built image].
- `libcurl` + `curl`, `cifs-utils`, `nfs-utils` are in the defconfig. `jose` and `luksmeta` exist in Buildroot, but **`clevis` and `tang` do not** (checked in the fork).
- **The kernel has no `DM_CRYPT`** for generic-x86-64: the fragments set `BLK_DEV_DM` and `DM_VERITY` only (`kernel/v6.18.y/haos.config`), the board fragment has nothing, and upstream `x86_64_defconfig` does not enable it. A kernel config change is needed (`DM_CRYPT`, XTS/AES-NI). `DM_CRYPT=m` exists only in the Rockchip fragment.

## 4. Proposed solution (generic-x86-64 only)

Opt-in. Default images and existing installs are unchanged.

1. **Format**: `hassos-data` becomes a LUKS2 container (aes-xts-plain64, argon2id keyslot for the passphrase; the network key goes in a separate keyslot). The ext4 label `hassos-data` lives *inside* the mapping (`/dev/mapper/hassos-data`), so label-based lookups work once it is open.
2. **Unlock service** (new, `haos-data-unlock.service`): fetches the key over the network, pipes it into `cryptsetup open --key-file=-` (the key never touches disk), and only then lets `mnt-data.mount` proceed.
3. **Late unlock, no initramfs** [H]. Because the network needs NetworkManager and the overlay, the unlock cannot happen in the current position of `mnt-data.mount` (before `local-fs.target`). Proposal: keep the kernel/rootfs mechanism as is and move `mnt-data.mount` out of `local-fs.target` for encrypted systems, ordered `After=network-online.target haos-data-unlock.service` and `Before=docker.service haos-supervisor.service`. Impact to solve: `var-log-journal.mount` is in `haos-bind.target` (before `sysinit.target`), so on encrypted systems the persistent journal would have to start volatile and be flushed after unlock; swap file and `docker-prepare` already start after the mount.
4. **Alternative**: initramfs with network (dracut-like or `CONFIG_INITRAMFS_SOURCE`, which would keep the artifact inside the kernel slot). It is cleaner for ordering but adds a new boot stage, a new thing to update through RAUC, and duplicates NetworkManager's Wi-Fi/VLAN configuration in early boot. Not recommended as a first step.
5. **Wired DHCP only for the first version.** Wi-Fi credentials live in the overlay and would be needed before unlock; with late unlock they are available, but a Wi-Fi-only box that fails to associate stays locked. Keep it simple: Ethernet recommended, Wi-Fi allowed but documented.

## 5. Where the key comes from

Decision to take with maintainers; ranking by implementation cost with what exists today [V for package availability]:

| Source | Needs | Notes |
|---|---|---|
| **HTTPS GET** of a key file, with a client certificate or bearer token stored in the overlay and a pinned CA | `curl`, present | Smallest change. Server can be any small service on the LAN (even a router/NAS reverse proxy). Revocation = delete the token server-side. |
| **SMB/NFS file** | `cifs-utils` / `nfs-utils`, present | Needs mount credentials in the overlay; heavier, more moving parts at boot. |
| **Tang (network-bound, clevis)** | New packages `clevis`, `tang` client deps (`jose`, `luksmeta` exist) | No key stored server-side, standard in the Linux world, but adds packages and a LUKS token plugin to maintain. Good second step. |
| **SSH token** (cryptsetup ssh-token) | `libssh` in Buildroot, rebuild of cryptsetup with the option | Uses a key kept in the clear on the machine; not appealing. |

Recommendation: define a small **pluggable "key provider" contract** (a command that prints the key on stdout, exit code 0 on success) with HTTPS as the first provider and Tang as a possible later one.

A property worth keeping whatever the source: **the key server must only be reachable from the home network**, so that a stolen machine powered on elsewhere cannot fetch the key.

## 6. When the key is unreachable

- Retry forever with backoff (a power cut often brings the PC back **before** the router or NAS). No timeout that leads to a wipe or a reformat, ever.
- Boot continues without data: Supervisor does not start (it requires `/mnt/data`), as with any missing data partition today. Console message and journal entry explain "waiting for key".
- A recovery passphrase (next section) can be entered from the console if someone is there, but the system must not **require** a keyboard.
- Open question for maintainers: should the Supervisor/UI have a read-only "locked, waiting for key" state? Today it simply is not running when the data partition is missing [H].

## 7. Recovery and backup of the key

- A second LUKS keyslot with a **recovery passphrase** generated at setup and shown once; the user stores it offline.
- Instructions to back up the LUKS header (`cryptsetup luksHeaderBackup`); a damaged header makes data unrecoverable.
- Procedure from a live system to open the volume by hand and copy data out.
- Key rotation and revocation (`luksChangeKey`, `luksKillSlot`) must be possible without reformatting.

## 8. What stays in clear

- ESP / `hassos-boot`: GRUB, `grubenv`, `cmdline.txt`, kernel slots, `rauc.db`.
- `hassos-system0/1` (erofs, public content).
- `hassos-bootstate`.
- **`hassos-overlay`: Wi-Fi PSK / NetworkManager connections, SSH host keys and `authorized_keys`, Bluetooth pairing keys, hostname.** The unlock configuration (key URL, client credential) also lives there. A thief therefore learns the home Wi-Fi password and the key server location. This is the main residual weakness and should be stated clearly. Encrypting the overlay as well would need the network *before* the overlay, i.e. an initramfs design.
- LUKS2 header metadata (cipher, keyslot count) and the partition layout.
- The size of the container (and, with `allow-discards`, a coarse pattern of used blocks) - open question whether to enable discard.

## 9. Migration of an existing installation

Two realistic paths, both opt-in and both needing a tested backup:

- **A. Via backup/restore** (safest, simplest to explain): create a full backup, switch the data partition to LUKS (new `haos.wipe`-like path that creates LUKS then ext4), restore. Cost: downtime and a backup that fits.
- **B. In-place `cryptsetup reencrypt --encrypt --reduce-device-size`** after shrinking the ext4 filesystem: no extra disk, but long, and not power-cut-safe unless the header/resume state is handled. Not recommended without maintainers' input.
- **C. Via the existing "move data disk" flow**: extend `migrate_disk` to create LUKS on the target. `haos-data` uses `e2image -ra` to a partition; it would write into the opened mapper device instead. Needs changes in Supervisor, os-agent and the scripts.

Things that assume the filesystem label is visible on the partition and would need adaptation [V that they exist; adaptation is H]: `haos-expand` (uses `lsblk pkname` on the labelled device to find the disk and partition number), `haos-data-disk-detach`, `haos-wipe`, Supervisor's `disabled_data_disk` / `multiple_data_disks` checks, os-agent's `GetRootDeviceFromLabel`.

Compatibility rule to decide: a downgrade to an OS slot without `DM_CRYPT` or the unlock service cannot open the data. RAUC slot B is the previous OS, so the first encrypted-capable release must exist in both slots before enabling encryption.

## 10. Open questions for maintainers

1. Is an opt-in encrypted data partition acceptable in principle for generic-x86-64? Any objection to adding `CONFIG_DM_CRYPT` (+ XTS/AES-NI) to its kernel?
2. Late unlock in the real root (section 4.3) versus an initramfs. Which is acceptable to maintain?
3. Which key source for the first version: HTTPS provider only, or Tang from the start?
4. Is it acceptable that overlay secrets (Wi-Fi PSK, SSH keys) remain in clear in this first version?
5. How should Supervisor, the UI and os-agent behave while the data disk is locked or when LUKS is on the label-matched partition? Who owns those changes (OS vs Supervisor vs os-agent)?
6. Migration: is backup/restore into a new LUKS partition enough, or is an in-place path expected?
7. Where should this live: Architecture Discussions / an ADR in `home-assistant/architecture` first, or directly an OS PR behind a build option?
8. Is a Secure Boot / measured boot story planned, which would change the threat model?

## 11. What this document does not claim

Nothing here has been built or run. Items marked **[H]** (late unlock ordering, presence of `systemd-cryptsetup` in the image, Supervisor behaviour when `/mnt/data` is absent, unlock timing on real hardware) are the first things a prototype would confirm.
