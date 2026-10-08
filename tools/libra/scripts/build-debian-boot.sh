#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build="$workspace/build"
case "${1:-}" in
	'') boot_only=0 ;;
	--boot-only) boot_only=1 ;;
	*) printf 'Usage: %s [--boot-only]\n' "$0" >&2; exit 2 ;;
esac
# Keep the established delivery/fastboot filename even though userspace is Debian.
cmdline='rdinit=/init console=tty0 panic=0 root=PARTLABEL=userdata rootfstype=f2fs rw'
cmdline="$cmdline msm.vram=32m clk_smd_rpm.skip_scaling=1 msm.fbdev=1 msm.mdp5_core_clk_rate=200000000"
cmdline="$cmdline log_buf_len=2M loglevel=4 clk_ignore_unused pd_ignore_unused libra.drm_native=1 libra.drm_auto=1 consoleblank=0"
cmdline="$cmdline qcom_tsens.msm8992_probe=1 clk_cpu_msm8992.clusters_probe=1 qcom_msm8992_cpufreq.enable=1"
# PCIe/firmware and Wi-Fi traffic verified on the phone; recovery boot stays archived.
cmdline="$cmdline libra.radio=1"
# Keep GPU power/IOMMU activation explicit during initial bring-up.
cmdline="$cmdline msm.gpu=0 qcom_iommu.msm8992_probe=0"
cmdline="$cmdline libra.gpu_defer=1"
python3 "$workspace/scripts/pack-factory-boot.py" \
 --factory "$workspace/libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img" \
 --kernel "$build/libra/arch/arm64/boot/Image" \
 --dtb "$build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb" \
 --ramdisk "$build/debian-libra-initrd.cpio.gz" \
 --cmdline "$cmdline" --output "$build/boot-libra-alpine-drm.img"
if [ "$boot_only" = 0 ]; then
	printf 'Packing fastboot sparse userdata image...\n'
	img2simg "$build/debian-trixie-arm64.f2fs.img" "$build/rootfs-libra-debian.img"
fi
(cd "$build" && sha256sum boot-libra-alpine-drm.img rootfs-libra-debian.img > debian-SHA256SUMS)
cat "$build/debian-SHA256SUMS"
