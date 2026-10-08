#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run sudo sh install.sh' >&2; exit 1; }
[ -r /usr/lib/libra-gpu/egl-vendor.json ] || {
 echo 'Install the matching FD418 GPU rootfs first.' >&2
 exit 1
}
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
(cd "$bundle" && sha256sum -c SHA256SUMS)
dpkg -i "$bundle"/debs/*.deb
cp -r --no-preserve=ownership "$bundle/files/." /
chmod 755 /usr/local/bin/libra-xfce-wayland-session /usr/local/bin/libra-desktop-setup \
 /usr/local/bin/libra-battery-setup /usr/local/bin/libra-keyboard /usr/local/bin/libra-desktop-action \
 /usr/sbin/libra-wayland /usr/sbin/libra-wayland-exit /usr/sbin/libra-wayland-return \
 /usr/sbin/libra-finalize-rootfs
systemctl daemon-reload
echo 'Wayland test session installed; Xfce X11 remains the default.'
echo 'Start: sudo libra-wayland start; return to X11: sudo libra-wayland stop'
