#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
alpine_version=3.24.2
alpine_branch=v3.24
build_dir="$workspace/build"
image="$build_dir/alpine-$alpine_version-aarch64.f2fs.img"
mount_dir="$workspace/rootfs"
archive="alpine-minirootfs-$alpine_version-aarch64.tar.gz"
url="https://dl-cdn.alpinelinux.org/alpine/$alpine_branch/releases/aarch64"
mkdir -p "$build_dir" "$mount_dir"
make -s -C "$workspace/linux" O="$build_dir/libra" ARCH=arm64 \
	CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" \
	INSTALL_HDR_PATH="$build_dir/libra-userspace-headers" headers_install
"${CROSS_COMPILE:-aarch64-linux-gnu-}gcc" -Os -Wall -Wextra -Werror \
	-fno-stack-protector -fno-asynchronous-unwind-tables -fno-unwind-tables \
	-nostdlib -static -I "$workspace/linux/tools/include/nolibc" \
	-isystem "$build_dir/libra-userspace-headers/include" -include nolibc.h \
	"$workspace/scripts/libra-kmsg.c" -o "$build_dir/libra-kmsg"
if mountpoint -q "$mount_dir"; then
	printf 'Refusing to use an already mounted rootfs: %s\n' "$mount_dir" >&2
	exit 1
fi
if [ -n "$(find "$mount_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
	printf 'Refusing to cover existing files in rootfs: %s\n' "$mount_dir" >&2
	exit 1
fi
if [ ! -f "$build_dir/$archive" ]; then
	curl -fL --retry 3 -o "$build_dir/$archive" "$url/$archive"
fi
if [ ! -f "$build_dir/$archive.sha256" ]; then
	curl -fL --retry 3 -o "$build_dir/$archive.sha256" "$url/$archive.sha256"
fi
(cd "$build_dir" && sha256sum -c "$archive.sha256")

# Only format a newly created, exact Alpine image path; preserve existing images.
if [ ! -e "$image" ]; then
	truncate -s 512M "$image"
	mkfs.f2fs -l alpine-test "$image"
fi
sudo -n mount -t f2fs -o loop "$image" "$mount_dir"
cleanup() {
	sudo -n umount "$mount_dir"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
if [ ! -e "$mount_dir/etc/alpine-release" ]; then
	sudo -n tar -xzf "$build_dir/$archive" -C "$mount_dir"
fi
sudo -n install -m 644 /etc/resolv.conf "$mount_dir/etc/resolv.conf"
# WSL binfmt_misc runs the aarch64 apk through the installed QEMU interpreter.
sudo -n chroot "$mount_dir" /sbin/apk add --no-cache openrc libdrm-tests kmod util-linux
# Install the modules from the same incremental build as the boot Image.
make -s -C "$workspace/linux" O="$build_dir/libra" ARCH=arm64 \
	CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" kernelrelease > "$build_dir/libra-kernelrelease.txt"
kernelrelease=$(cat "$build_dir/libra-kernelrelease.txt")
if [ ! -s "$build_dir/libra/modules.order" ]; then
	printf 'Kernel modules are missing; run build-libra.sh first.\n' >&2
	exit 1
fi
# Remove only stale module versions in this dedicated Alpine test image.
sudo -n rm -rf "$mount_dir/lib/modules"
sudo -n make -C "$workspace/linux" O="$build_dir/libra" ARCH=arm64 \
	CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" \
	INSTALL_MOD_PATH="$mount_dir" modules_install
sudo -n rm -f "$mount_dir/lib/modules/$kernelrelease/build" \
	"$mount_dir/lib/modules/$kernelrelease/source"
sudo -n chroot "$mount_dir" /sbin/depmod "$kernelrelease"
for module in msm qcom_labibb_regulator qcom_wled panel_sharp_libra_rsp61322; do
	sudo -n chroot "$mount_dir" /sbin/modprobe --set-version "$kernelrelease" \
		--show-depends "$module"
done
sudo -n install -m 755 "$workspace/scripts/alpine-init.sh" "$mount_dir/init"
sudo -n install -m 755 "$workspace/scripts/alpine-usb-gadget.sh" \
	"$mount_dir/usr/sbin/libra-usb-gadget"
sudo -n install -m 755 "$workspace/scripts/alpine-drm-test.sh" \
	"$mount_dir/usr/sbin/libra-drm-test"
sudo -n install -m 755 "$workspace/scripts/alpine-drm-load.sh" \
	"$mount_dir/usr/sbin/libra-drm-load"
sudo -n install -m 755 "$build_dir/libra-kmsg" "$mount_dir/usr/sbin/libra-kmsg"
# The kernel opens these before /init has mounted devtmpfs.
sudo -n mkdir -p "$mount_dir/dev"
if [ ! -e "$mount_dir/dev/console" ]; then
	sudo -n mknod -m 600 "$mount_dir/dev/console" c 5 1
fi
if [ ! -e "$mount_dir/dev/null" ]; then
	sudo -n mknod -m 666 "$mount_dir/dev/null" c 1 3
fi
sudo -n chroot "$mount_dir" /bin/sh -n /init
sudo -n chroot "$mount_dir" /bin/sh -n /usr/sbin/libra-usb-gadget
sudo -n chroot "$mount_dir" /bin/sh -n /usr/sbin/libra-drm-test
sudo -n chroot "$mount_dir" /bin/sh -n /usr/sbin/libra-drm-load
sudo -n chroot "$mount_dir" /bin/busybox --list | awk '
	{ present[$0] = 1 }
	END {
		split("getty setsid sh", required, " ")
		for (i in required) {
			if (!present[required[i]]) {
				printf "Missing initrd applet: %s\n", required[i] > "/dev/stderr"
				failed = 1
			}
		}
		exit failed
	}
'
sudo -n sh -c 'cd "$1" && find . -xdev -print0 | cpio --null -o -H newc --quiet --owner=0:0' \
	sh "$mount_dir" | gzip -n -9 > "$build_dir/alpine-libra-initrd.cpio.gz"
printf 'Built %s\n' "$build_dir/alpine-libra-initrd.cpio.gz"
