#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output="$workspace/build"
kernel="$output/libra/arch/arm64/boot/Image"
dtb="$output/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb"
ramdisk="$output/alpine-libra-initrd.cpio.gz"
rpm_skip_scaling=${RPM_SKIP_SCALING:-1}
drm_auto=${DRM_AUTO:-1}
for option in "$rpm_skip_scaling" "$drm_auto"; do
	case "$option" in
		0|1) ;;
		*) printf 'RPM_SKIP_SCALING and DRM_AUTO must be 0 or 1\n' >&2; exit 2 ;;
	esac
done
cmdline="rdinit=/init console=tty0 panic=0 msm.vram=32m clk_smd_rpm.skip_scaling=$rpm_skip_scaling"
cmdline="$cmdline msm.fbdev=$drm_auto msm.mdp5_core_clk_rate=200000000"
cmdline="$cmdline log_buf_len=2M loglevel=4 clk_ignore_unused pd_ignore_unused"
cmdline="$cmdline libra.drm_native=1 libra.drm_auto=$drm_auto"
factory="$workspace/libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img"
for required in "$kernel" "$ramdisk" "$dtb"; do
	if [ ! -s "$required" ]; then
		printf 'Missing build input: %s\n' "$required" >&2
		exit 1
	fi
done
python3 "$workspace/scripts/pack-factory-boot.py" --factory "$factory" \
	--kernel "$kernel" --ramdisk "$ramdisk" --dtb "$dtb" \
	--cmdline "$cmdline" --output "$output/boot-libra-alpine-drm.img"
sha256sum "$output/boot-libra-alpine-drm.img"
