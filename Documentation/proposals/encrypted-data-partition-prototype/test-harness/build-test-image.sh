#!/bin/bash
# ==============================================================================
# Build a test image for the encrypted data partition prototype, WITHOUT a
# Buildroot build: start from an official generic-x86-64 release image and
#   - add dm-crypt/xts/essiv modules built for the release kernel,
#   - add the prototype files from this branch to the erofs rootfs,
#   - replace hassos-data by a LUKS2 container holding the original ext4,
#   - put the unlock configuration on the overlay partition,
#   - add "haos.data-crypt=1 console=ttyS0" to cmdline.txt.
#
# Test-only. Never run against a disk or an image used in production.
#
# Usage: build-test-image.sh <release.img> <modules-dir> <keys-dir> <out.img> [disk-size]
#   modules-dir: contains dm-crypt.ko xts.ko essiv.ko for the release kernel
#   keys-dir:    output of key-server.py --init (net.key, ca.pem, token, url)
# Requires: root, sgdisk, erofs-utils, cryptsetup, mtools, e2fsprogs, kmod,
#           python3-cryptography, qemu-img
# ==============================================================================
set -euo pipefail

SRC_IMG="$(realpath "$1")"
MOD_DIR="$(realpath "$2")"
KEYS_DIR="$(realpath "$3")"
OUT_IMG="$(realpath -m "$4")"
DISK_SIZE="${5:-6G}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${HERE}/../../../.." && pwd)"
OVERLAY_SRC="${REPO}/buildroot-external/rootfs-overlay"
RECOVERY_PASSPHRASE="${RECOVERY_PASSPHRASE:-recovery-passphrase-for-tests-only}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/haos-crypt-XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

part_start() { sgdisk -i "$1" "${OUT_IMG}" | awk '/First sector/ {print $3}'; }
part_size()  { sgdisk -i "$1" "${OUT_IMG}" | awk '/Partition size/ {print $3}'; }
extract()    { dd if="${OUT_IMG}" of="$2" bs=512 skip="$(part_start "$1")" count="$(part_size "$1")" status=none; }
inject()     { dd if="$2" of="${OUT_IMG}" bs=512 seek="$(part_start "$1")" conv=notrunc status=none; }

echo "[1/6] Copy release image"
cp --sparse=always "${SRC_IMG}" "${OUT_IMG}"
# partition numbers of the generic-x86-64 GPT layout
P_BOOT=1 P_SYSTEM0=3 P_OVERLAY=7 P_DATA=8

echo "[2/6] Rebuild rootfs (system0) with modules and prototype files"
extract "${P_SYSTEM0}" "${WORK}/system0.erofs"
mkdir "${WORK}/rootfs"
fsck.erofs --extract="${WORK}/rootfs" "${WORK}/system0.erofs" > /dev/null
KVER="$(ls "${WORK}/rootfs/lib/modules")"
install -D -m 0644 -t "${WORK}/rootfs/lib/modules/${KVER}/updates" "${MOD_DIR}"/*.ko
depmod -b "${WORK}/rootfs" "${KVER}"
for f in \
    usr/lib/systemd/system-generators/haos-data-crypt-generator \
    usr/lib/systemd/system/haos-data-unlock.service \
    usr/lib/systemd/system/haos-data-crypt-post.service \
    usr/libexec/haos-data-unlock \
    usr/libexec/haos-expand; do
    install -D -m "$(stat -c %a "${OVERLAY_SRC}/${f}")" "${OVERLAY_SRC}/${f}" "${WORK}/rootfs/${f}"
done
# The release uses lz4hc+lzma with compress hints (BR2_TARGET_ROOTFS_EROFS_*).
# With the erofs-utils 1.7 of the build host that does not fit in 256 MiB,
# so use lzma for everything (slower boot, fine for a test VM).
mkfs.erofs -zlzma,9 -Eztailpacking,fragments,dedupe -C262144 \
    "${WORK}/system0.new" "${WORK}/rootfs" > /dev/null
if [ "$(stat -c %s "${WORK}/system0.new")" -gt "$(( $(part_size ${P_SYSTEM0}) * 512 ))" ]; then
    echo "rootfs does not fit in the system partition" >&2
    exit 1
fi
inject "${P_SYSTEM0}" "${WORK}/system0.new"

echo "[3/6] Convert data partition to LUKS2"
extract "${P_DATA}" "${WORK}/data.ext4"
LUKS_OFFSET=$((16 * 1024 * 1024))
# The release ext4 is already at its minimum size, so make room for the
# LUKS2 header by growing the partition by LUKS_OFFSET (same start, name,
# type and PARTUUID). The rest of the disk is left for haos-expand.
qemu-img resize -q -f raw "${OUT_IMG}" "${DISK_SIZE}"
sgdisk -e "${OUT_IMG}" > /dev/null
D_START="$(part_start ${P_DATA})"
D_SIZE="$(part_size ${P_DATA})"
D_GUID="$(sgdisk -i ${P_DATA} "${OUT_IMG}" | awk '/unique GUID/ {print $4}')"
D_TYPE="$(sgdisk -i ${P_DATA} "${OUT_IMG}" | awk '/Partition GUID code/ {print $4}')"
sgdisk -d ${P_DATA} \
    -n ${P_DATA}:"${D_START}":$(( D_START + D_SIZE + LUKS_OFFSET / 512 - 1 )) \
    -c ${P_DATA}:hassos-data -t ${P_DATA}:"${D_TYPE}" -u ${P_DATA}:"${D_GUID}" \
    "${OUT_IMG}" > /dev/null
DATA_BYTES="$(( $(part_size ${P_DATA}) * 512 ))"
truncate -s "${DATA_BYTES}" "${WORK}/data.luks"
# Slot 0: random network key (high entropy, cheap PBKDF is fine).
cryptsetup luksFormat -q --type luks2 --cipher aes-xts-plain64 --key-size 512 \
    --sector-size 512 --offset $((LUKS_OFFSET / 512)) \
    --pbkdf pbkdf2 --pbkdf-force-iterations 1000 \
    --key-slot 0 --key-file "${KEYS_DIR}/net.key" "${WORK}/data.luks"
# Slot 1: recovery passphrase (memory-hard PBKDF; reduced here for a TCG VM).
printf '%s' "${RECOVERY_PASSPHRASE}" > "${WORK}/recovery"
cryptsetup luksAddKey -q --key-file "${KEYS_DIR}/net.key" --key-slot 1 \
    --pbkdf argon2id --pbkdf-memory 65536 --pbkdf-force-iterations 4 --pbkdf-parallel 1 \
    "${WORK}/data.luks" "${WORK}/recovery"
cryptsetup luksDump -q --dump-volume-key --volume-key-file "${WORK}/vk" \
    --key-file "${KEYS_DIR}/net.key" "${WORK}/data.luks" > /dev/null
python3 "${HERE}/luks_encrypt_offline.py" "${WORK}/data.ext4" "${WORK}/data.luks" \
    "${WORK}/vk" "${LUKS_OFFSET}"
shred -u "${WORK}/vk"
inject "${P_DATA}" "${WORK}/data.luks"

echo "[4/6] Unlock configuration on overlay"
extract "${P_OVERLAY}" "${WORK}/overlay.ext4"
cat > "${WORK}/debugfs.cmd" <<EOF
mkdir etc
mkdir etc/haos-data-crypt
write ${KEYS_DIR}/url etc/haos-data-crypt/key-url
write ${KEYS_DIR}/ca.pem etc/haos-data-crypt/ca.pem
write ${KEYS_DIR}/token etc/haos-data-crypt/token
sif etc/haos-data-crypt mode 040700
sif etc/haos-data-crypt/token mode 0100600
sif etc/haos-data-crypt/key-url mode 0100644
sif etc/haos-data-crypt/ca.pem mode 0100644
EOF
debugfs -w -f "${WORK}/debugfs.cmd" "${WORK}/overlay.ext4" > /dev/null 2>&1
inject "${P_OVERLAY}" "${WORK}/overlay.ext4"

echo "[5/6] Kernel command line"
extract "${P_BOOT}" "${WORK}/boot.vfat"
mcopy -o -i "${WORK}/boot.vfat" ::cmdline.txt "${WORK}/cmdline.txt"
if ! grep -q "haos.data-crypt=1" "${WORK}/cmdline.txt"; then
    sed -i '1 s/$/ console=ttyS0 haos.data-crypt=1/' "${WORK}/cmdline.txt"
fi
mcopy -o -i "${WORK}/boot.vfat" "${WORK}/cmdline.txt" ::cmdline.txt
inject "${P_BOOT}" "${WORK}/boot.vfat"
echo "    cmdline.txt: $(cat "${WORK}/cmdline.txt")"

echo "[6/6] Disk size ${DISK_SIZE}; data partition grows on first boot (haos-expand)"
echo "Done: ${OUT_IMG}"
