#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build the real Debian root only inside its mounted F2FS image.
set -eu
workspace=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build="$workspace/build"
image="$build/debian-trixie-arm64.f2fs.img"
root="$workspace/rootfs"
mirror=${DEBIAN_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn/debian}
mkdir -p "$build" "$root"
if mountpoint -q "$root" || [ -n "$(find "$root" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
	printf 'rootfs/ must be empty and unmounted.\n' >&2
	exit 1
fi
if [ ! -e "$image" ]; then
	truncate -s 4G "$image"
	mkfs.f2fs -f -l libra-debian "$image"
fi
sudo -n mount -t f2fs -o loop "$image" "$root"
# mkfs.f2fs/old overlays may inherit the build user UID for the root inode.
sudo -n chown 0:0 "$root"
cleanup() {
	for path in dev/pts dev proc sys; do
		if mountpoint -q "$root/$path"; then sudo -n umount "$root/$path"; fi
	done
	sudo -n umount "$root"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
if [ ! -e "$root/etc/debian_version" ] && [ ! -e "$root/debootstrap/debootstrap" ]; then
	sudo -n debootstrap --arch=arm64 --foreign --variant=minbase \
		--include=ca-certificates trixie "$root" "$mirror"
fi
# Package installation must never start services on the build host.
sudo -n mkdir -p "$root/usr/sbin"
printf '#!/bin/sh\nexit 101\n' | sudo -n tee "$root/usr/sbin/policy-rc.d" >/dev/null
sudo -n chmod 755 "$root/usr/sbin/policy-rc.d"
if [ -e "$root/debootstrap/debootstrap" ]; then
	sudo -n chroot "$root" /debootstrap/debootstrap --second-stage
fi
sudo -n mount --bind /dev "$root/dev"
sudo -n mount -t devpts devpts "$root/dev/pts"
sudo -n mount -t proc proc "$root/proc"
sudo -n mount -t sysfs -o ro sysfs "$root/sys"
sudo -n install -m 644 /etc/resolv.conf "$root/etc/resolv.conf"
sudo -n env DEBIAN_FRONTEND=noninteractive chroot "$root" /bin/sh \
	< "$workspace/scripts/configure-debian-rootfs.sh"
release=$(make -s -C "$workspace/linux" O="$build/libra" ARCH=arm64 \
	CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" kernelrelease)
sudo -n make -s -C "$workspace/linux" O="$build/libra" ARCH=arm64 \
	CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}" \
	INSTALL_MOD_PATH="$root" modules_install
sudo -n rm -f "$root/lib/modules/$release/build" "$root/lib/modules/$release/source"
sudo -n chroot "$root" depmod "$release"
for helper in drm-load drm-test drm-console; do
	sudo -n install -m 755 "$workspace/scripts/alpine-$helper.sh" "$root/usr/sbin/libra-$helper"
done
sudo -n install -m 755 "$build/libra-kmsg" "$root/usr/sbin/libra-kmsg"
python3 "$workspace/scripts/extract-libra-radio-firmware.py"
sudo -n cp -r --no-preserve=ownership "$build/libra-radio-firmware/." "$root/usr/lib/firmware/"
python3 "$workspace/scripts/extract-libra-gpu-firmware.py"
sudo -n cp -r --no-preserve=ownership "$build/libra-gpu-firmware/qcom" "$root/usr/lib/firmware/"
"${CROSS_COMPILE:-aarch64-linux-gnu-}gcc" -Os -Wall -Wextra -Werror \
	-fno-stack-protector -fno-asynchronous-unwind-tables -fno-unwind-tables \
	-nostdlib -static -I "$workspace/linux/tools/include/nolibc" \
	-isystem "$build/libra/usr/include" -include nolibc.h \
	"$workspace/linux/tools/libra/tests/gpu-probe.c" -o "$build/libra-gpu-probe"
sudo -n install -m 755 "$build/libra-gpu-probe" "$root/usr/sbin/libra-gpu-probe"
sudo -n chroot "$root" dpkg-query -W -f='${binary:Package}\n' > "$build/libra-mesa-packages-before.txt"
sudo -n env DEBIAN_FRONTEND=noninteractive chroot "$root" apt-get install -y \
	libc6-dev libdrm-dev libexpat1-dev libzstd-dev zlib1g-dev libelf-dev \
	libegl-dev libgles-dev libglvnd-dev libstdc++-14-dev \
	libx11-xcb-dev libxext-dev libxrandr-dev libxfixes-dev libxxf86vm-dev \
	libxcb-glx0-dev libxcb-dri2-0-dev libxcb-dri3-dev \
	libxcb-present-dev libxcb-randr0-dev libxcb-xfixes0-dev libxcb-shm0-dev \
	libxcb-sync-dev libxshmfence-dev libwayland-dev libwayland-egl-backend-dev wayland-protocols
python3 "$workspace/scripts/build-libra-mesa.py" --root "$root"
sudo -n mkdir -p "$root/usr/lib/libra-gpu/dri"
mesa_abi=$(sudo -n chroot "$root" dpkg-query -W -f='${Version}' libegl-mesa0)
sudo -n install -m 755 "$build/libra-mesa/src/gallium/targets/dri/libgallium-$mesa_abi.so" \
	"$root/usr/lib/libra-gpu/dri/libgallium-25.0.7-libra-a418.so"
sudo -n install -m 755 "$build/libra-mesa/src/egl/libEGL_mesa.so.0.0.0" \
	"$root/usr/lib/libra-gpu/dri/libEGL_mesa.so.0"
sudo -n install -m 755 "$build/libra-mesa/src/glx/libGLX_mesa.so.0.0.0" \
	"$root/usr/lib/libra-gpu/dri/libGLX_mesa.so.0"
sudo -n install -m 755 "$build/libra-mesa/src/gbm/libgbm.so.1.0.0" \
	"$root/usr/lib/libra-gpu/dri/libgbm.so.1"
sudo -n install -m 755 "$build/libra-mesa/src/gbm/backends/dri/dri_gbm.so" \
	"$root/usr/lib/libra-gpu/dri/dri_gbm.so"
for driver in msm swrast; do
	sudo -n ln -sfn libgallium-25.0.7-libra-a418.so "$root/usr/lib/libra-gpu/dri/${driver}_dri.so"
done
sudo -n ln -sfn libgallium-25.0.7-libra-a418.so \
	"$root/usr/lib/libra-gpu/dri/libgallium-$mesa_abi.so"
# Cross compiler supplies instructions; Debian supplies headers and runtime.
"${CROSS_COMPILE:-aarch64-linux-gnu-}gcc" --sysroot="$root" \
	-B"$root/usr/lib/aarch64-linux-gnu/" -B"$root/usr/lib/gcc/aarch64-linux-gnu/14/" \
	-isystem "$root/usr/include/aarch64-linux-gnu" -L"$build/libra-mesa-link-compat" \
	-L"$root/usr/lib/aarch64-linux-gnu" -L"$root/usr/lib/gcc/aarch64-linux-gnu/14" \
	-Wl,-rpath-link,"$root/usr/lib/aarch64-linux-gnu" -O2 -Wall -Wextra -Werror \
	"$workspace/linux/tools/libra/tests/gpu-render.c" -lEGL -lGLESv2 -o "$build/libra-gpu-render"
sudo -n install -m 755 "$build/libra-gpu-render" "$root/usr/sbin/libra-gpu-render"
python3 - "$root" "$build/libra-mesa-packages-before.txt" <<'PY'
from pathlib import Path
import subprocess, sys
root, before = sys.argv[1:]
old = set(Path(before).read_text().splitlines())
current = subprocess.check_output(['sudo', '-n', 'chroot', root, 'dpkg-query', '-W',
    '-f=${db:Status-Status}\t${binary:Package}\n'], text=True)
remove = [line.split('\t')[1] for line in current.splitlines()
          if line.startswith('installed\t') and line.split('\t')[1] not in old
          and line.split('\t')[1].split(':')[0].endswith('-dev')]
if remove:
    subprocess.run(['sudo', '-n', 'chroot', root, 'apt-get', 'purge', '-y', *remove], check=True)
PY
# Overlay files originate in a user checkout; never transfer that ownership.
sudo -n cp -r --no-preserve=ownership "$workspace/linux/tools/libra/debian/." "$root/"
sudo -n chmod 755 "$root/usr/sbin/libra-finalize-rootfs"
sudo -n chroot "$root" /usr/sbin/libra-finalize-rootfs
sudo -n chroot "$root" dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n' \
	> "$build/debian-package-manifest.tsv"
python3 "$workspace/scripts/build-debian-initrd.py" "$root"
sudo -n chroot "$root" apt-get clean
sudo -n rm -f "$root/usr/sbin/policy-rc.d" "$root/etc/ssh/ssh_host_"*
sudo -n truncate -s 0 "$root/etc/machine-id"
sudo -n rm -f "$root/var/lib/dbus/machine-id" "$root/var/lib/systemd/random-seed"
# WSL's resolver is only a build-time input; restore the delivered DNS settings.
printf 'nameserver 223.5.5.5\nnameserver 1.1.1.1\n' | sudo -n tee "$root/etc/resolv.conf" >/dev/null
sync
sudo -n fstrim "$root"
printf 'Built %s\n' "$image"
