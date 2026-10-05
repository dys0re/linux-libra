#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output="$workspace/build"
kernel="$output/libra/arch/arm64/boot/Image"
dtb_dir="$output/libra/arch/arm64/boot/dts/qcom"
ramdisk="$output/alpine-libra-initrd.cpio.gz"
rpm_skip_scaling=${RPM_SKIP_SCALING:-1}
case "$rpm_skip_scaling" in
	0|1) ;;
	*) printf 'RPM_SKIP_SCALING must be 0 or 1\n' >&2; exit 2 ;;
esac
cmdline="rdinit=/init console=tty0 panic=0 msm.vram=32m clk_smd_rpm.skip_scaling=$rpm_skip_scaling"
factory="$workspace/libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img"
for required in "$kernel" "$ramdisk" \
	"$dtb_dir/msm8992-xiaomi-libra-drm-late.dtb" "$dtb_dir/msm8992-xiaomi-libra-simplefb.dtb"; do
	if [ ! -s "$required" ]; then
		printf 'Missing build input: %s\n' "$required" >&2
		exit 1
	fi
done
for variant in drm simplefb; do
	case "$variant" in
		# DRM, bias and backlight are modules, loaded explicitly over ACM.
		# Keep the firmware display powered until that handover.
		drm) dtb=msm8992-xiaomi-libra-drm-late.dtb; extra='msm.fbdev=0 msm.mdp5_core_clk_rate=200000000 drm.debug=0x6 log_buf_len=2M loglevel=4 clk_ignore_unused pd_ignore_unused libra.drm_late=1' ;;
		simplefb) dtb=msm8992-xiaomi-libra-simplefb.dtb; extra='loglevel=8 ignore_loglevel' ;;
	esac
	python3 "$workspace/scripts/pack-factory-boot.py" --factory "$factory" \
		--kernel "$kernel" --ramdisk "$ramdisk" --dtb "$dtb_dir/$dtb" \
		--cmdline "$cmdline $extra" --output "$output/boot-libra-alpine-$variant.img"
done
sha256sum "$output"/boot-libra-alpine-drm.img \
	"$output"/boot-libra-alpine-simplefb.img
