#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Install matching modules and OEM GPU firmware; never activates the GPU.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with sudo sh install.sh' >&2; exit 1; }
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
(cd "$bundle" && sha256sum -c SHA256SUMS)
dpkg -i "$bundle"/debs/*.deb
cp -r --no-preserve=ownership "$bundle/files/." /
depmod 6.12.112+
systemctl daemon-reload
echo 'GPU bring-up files installed. Start the matching boot; activation is manual.'
