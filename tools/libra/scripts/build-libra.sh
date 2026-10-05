#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu

workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
kernel_tree="$workspace/linux"
output_dir="$workspace/build/libra"
fragment="$workspace/cfg/msm8992-libra.config"
cross_compile=${CROSS_COMPILE:-aarch64-linux-gnu-}
build_jobs=${JOBS:-10}

mkdir -p "$output_dir"
if [ ! -f "$output_dir/.config" ]; then
	make -C "$kernel_tree" O="$output_dir" ARCH=arm64 \
		CROSS_COMPILE="$cross_compile" KCONFIG_ALLCONFIG="$fragment" allnoconfig
else
	"$kernel_tree/scripts/kconfig/merge_config.sh" -m -O "$output_dir" \
		"$output_dir/.config" "$fragment"
	make -C "$kernel_tree" O="$output_dir" ARCH=arm64 \
		CROSS_COMPILE="$cross_compile" olddefconfig
fi

# Kconfig silently discards requests whose parent menus/dependencies are off.
# Check the effective configuration before compiling a misleading test image.
awk '
	FNR == NR {
		if ($0 ~ /^CONFIG_/) {
			split($0, value, "=")
			wanted[value[1]] = value[2]
		}
		next
	}
	/^CONFIG_/ {
		split($0, value, "=")
		actual[value[1]] = value[2]
	}
	/^# CONFIG_.* is not set$/ { actual[$2] = "n" }
	END {
		for (key in wanted) {
			if (wanted[key] == "n" && actual[key] == "")
				continue
			if (wanted[key] != actual[key]) {
				printf "%s: requested %s, effective %s\n", key,
				       wanted[key], actual[key] == "" ? "absent" : actual[key] > "/dev/stderr"
				failed = 1
			}
		}
		exit failed
	}
' "$fragment" "$output_dir/.config"

if [ "$#" -eq 0 ]; then
	set -- Image modules qcom/msm8992-xiaomi-libra.dtb \
		qcom/msm8992-xiaomi-libra-simplefb.dtb qcom/msm8992-xiaomi-libra-drm-late.dtb
fi
exec make -C "$kernel_tree" O="$output_dir" ARCH=arm64 \
	CROSS_COMPILE="$cross_compile" -j"$build_jobs" "$@"
