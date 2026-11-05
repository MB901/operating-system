#!/usr/bin/env python3
"""Encrypt an ext4 image into an existing LUKS2 container, offline.

Test fixture only. The build host used for the prototype has no
device-mapper, so `cryptsetup open` + `dd` is not possible. Instead the
volume key is dumped with `cryptsetup luksDump --dump-volume-key` and the
plaintext is encrypted here with AES-XTS-plain64, 512-byte sectors, which
is what dm-crypt does for a LUKS2 segment created with
`--cipher aes-xts-plain64 --sector-size 512`.

On a real system the conversion would be done by cryptsetup itself
(`cryptsetup reencrypt --encrypt` or open + copy); this script only exists
to build a test image.

Usage: luks_encrypt_offline.py <plain.ext4> <container.luks> <volume-key-file> <data-offset-bytes>
"""

import os
import sys
from concurrent.futures import ProcessPoolExecutor

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SECTOR = 512
CHUNK_SECTORS = 8192  # 4 MiB per work item


def encrypt_chunk(args: tuple[bytes, int, bytes]) -> tuple[int, bytes]:
    key, first_sector, data = args
    out = bytearray(len(data))
    for i in range(0, len(data), SECTOR):
        sector = first_sector + i // SECTOR
        tweak = sector.to_bytes(16, "little")  # plain64 IV
        enc = Cipher(algorithms.AES(key), modes.XTS(tweak)).encryptor()
        out[i : i + SECTOR] = enc.update(data[i : i + SECTOR]) + enc.finalize()
    return first_sector, bytes(out)


def main() -> None:
    plain, container, vk_file, offset = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    with open(vk_file, "rb") as f:
        key = f.read()
    if len(key) != 64:
        sys.exit(f"expected a 512-bit XTS key, got {len(key) * 8} bits")

    size = os.path.getsize(plain)
    if size % SECTOR:
        sys.exit("plaintext size is not a multiple of 512")
    if os.path.getsize(container) < offset + size:
        sys.exit("container too small")

    def work():
        with open(plain, "rb") as f:
            sector = 0
            while chunk := f.read(CHUNK_SECTORS * SECTOR):
                yield key, sector, chunk
                sector += len(chunk) // SECTOR

    with open(container, "r+b") as out, ProcessPoolExecutor() as pool:
        for first_sector, data in pool.map(encrypt_chunk, work(), chunksize=1):
            out.seek(offset + first_sector * SECTOR)
            out.write(data)
    print(f"encrypted {size} bytes at offset {offset}")


if __name__ == "__main__":
    main()
