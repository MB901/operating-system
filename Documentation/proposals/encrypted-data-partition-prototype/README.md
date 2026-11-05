# Prototype: encrypted data partition with a network key

Throw-away prototype for [the design notes](../encrypted-data-partition.md). It is not meant to be merged as is.

## What is in the branch

| File | Role |
|---|---|
| `buildroot-external/board/pc/generic-x86-64/kernel.config` | `DM_CRYPT`, `CRYPTO_XTS`, `CRYPTO_AES_NI_INTEL` (`=y`; not built, see below) |
| `rootfs-overlay/usr/lib/systemd/system-generators/haos-data-crypt-generator` | Only with `haos.data-crypt=1`: moves `/mnt/data` and its consumers after the unlock, disables data disk move and detach; with `haos.wipe=1` it does nothing, so the stock units and `haos-wipe` run |
| `rootfs-overlay/usr/lib/systemd/system/haos-data-unlock.service` | Runs the unlock after `network-online.target` |
| `rootfs-overlay/usr/libexec/haos-data-unlock` | HTTPS or Tang provider, plus a recovery passphrase prompt on the console; retries forever |
| `rootfs-overlay/usr/lib/systemd/system/haos-data-crypt-post.service` | tmpfiles for `/mnt/data`, persistent journal bind and flush |
| `rootfs-overlay/usr/libexec/haos-wipe` | With `haos.data-crypt=1`: waits for the partition device, erases the LUKS2 keyslots and header, removes both flags from `cmdline.txt` |
| `rootfs-overlay/usr/libexec/haos-expand` | Grows the partition under a dm-crypt mapping, then `cryptsetup resize` |
| `test-harness/` | Builds a test image from a release image and boots scenarios in QEMU |

## Test harness (test only, never on a production disk)

Requirements (Ubuntu 24.04, root, no KVM needed): `qemu-system-x86 qemu-utils ovmf erofs-utils cryptsetup-bin mtools gdisk e2fsprogs kmod python3-cryptography`, plus `tang clevis jose socat` for Tang.

1. Download the release image `haos_generic-x86-64-18.4.img.xz` and the matching kernel source (`linux-6.18.58`).
2. Get the kernel config from the release `bzImage` (`scripts/extract-ikconfig`, needs `lz4`). Then enable `DM_CRYPT=m` and `CRYPTO_XTS=m`, run `make olddefconfig modules_prepare`, and build `drivers/md/dm-crypt.ko`, `crypto/xts.ko` and `crypto/essiv.ko`. The vermagic must read `6.18.58-haos SMP preempt mod_unload`.
3. Run `key-server.py --init keys --ip 10.0.2.2` for HTTPS. For Tang, run `tang-server.sh init tang`, then start `tang-server.sh serve tang`, then `tang-server.sh jwe tang http://10.0.2.2:8888 keys/net.key key.jwe`.
4. Build the image with `WITH_CLEVIS=1 build-test-image.sh <release.img> <modules-dir> keys https.img 6G`. For Tang, add `KEY_JWE=key.jwe` and reuse the rootfs with `SYSTEM0_IMAGE=https.system0.erofs`.
5. Run `run-scenarios.py https.img keys <workdir> key-ok key-denied key-late locked-reboots`, and `run-scenarios.py tang.img tang <workdir> tang`.

The data partition is converted offline because the build host has no device-mapper. `luks_encrypt_offline.py` encrypts the ext4 with the volume key (AES-XTS-plain64, 512-byte sectors). The rootfs is rebuilt with `mkfs.erofs -zlzma`, because the release's lz4hc+lzma settings do not fit in 256 MiB with erofs-utils 1.7.

Results: [`RESULTS.md`](RESULTS.md).
