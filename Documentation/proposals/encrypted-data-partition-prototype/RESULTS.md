# Prototype results

All runs happened in QEMU VMs (TCG, no KVM, 4 vCPU, 2 GiB RAM, OVMF) on a cloud build host, never on a real installation. Images were made from the official `haos_generic-x86-64-18.4.img` with `test-harness/build-test-image.sh`. Raw logs (serial consoles, per-scenario `results.md`) stayed on the build host. The excerpts below are copied from them.

**Test-only components, not representative of a Buildroot build:**

- `dm-crypt.ko`, `xts.ko` and `essiv.ko` were built out of tree against the release kernel config; the `=y` kernel fragment was not compiled.
- `clevis`, `jose`, `libjose`, `libjansson`, GNU `bash`, `libtinfo` and `resize2fs` were **copied from Ubuntu 24.04** into the rootfs. Their sizes below are measurements of those Ubuntu binaries, **not of Buildroot packages**.
- The data partition of the "already encrypted" images was converted offline by the harness. The `migrate` scenario is the one where HAOS itself converts a plain installation.
- The rootfs is recompressed with `mkfs.erofs -zlzma`, so boot timings are not comparable to the release image.
- The VM has no Internet access: Supervisor stays in `setup` (no Core install), which matters for the boot counter (see below).

## Summary

RESULTS_SUMMARY_PLACEHOLDER

## Details

RESULTS_DETAILS_PLACEHOLDER
