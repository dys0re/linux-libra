#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Offline userspace addition for an existing Debian Libra userdata.
set -eu
[ "$(id -u)" = 0 ] || { printf 'Run with sudo sh install.sh\n' >&2; exit 1; }
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
(cd "$bundle" && sha256sum -c SHA256SUMS)
dpkg -i "$bundle"/debs/*.deb
install -m 755 "$bundle/libra-battery-setup" /usr/local/bin/libra-battery-setup
install -m 755 "$bundle/libra-battery-status" /usr/sbin/libra-battery-status
install -m 755 "$bundle/libra-desktop-setup" /usr/local/bin/libra-desktop-setup
rm -f /home/libra/.config/autostart/xfce4-power-manager.desktop
printf 'Battery userspace installed. Boot the matching battery image; the desktop applies settings at login.\n'
