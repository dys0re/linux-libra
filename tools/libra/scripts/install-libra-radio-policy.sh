#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$base"
sha256sum --quiet -c SHA256SUMS
install -d -m 755 /var/lib/libra/firmware-backup
old=/var/lib/libra/firmware-backup/firmware-5.before-oem-policy.bin
if [ ! -f "$old" ]; then
 cp /usr/lib/firmware/ath10k/QCA6174/hw3.0/firmware-5.bin "$old"
fi
install -m 644 "$base/firmware-5.bin" /usr/lib/firmware/ath10k/QCA6174/hw3.0/firmware-5.bin
install -m 644 "$base/libra-oem-radio-manifest.json" /usr/lib/firmware/libra-oem-radio-manifest.json
install -m 755 "$base/libra-radio-start" /usr/sbin/libra-radio-start
update-alternatives --set regulatory.db /lib/firmware/regulatory.db-upstream
sha256sum /usr/lib/firmware/ath10k/QCA6174/hw3.0/firmware-5.bin
sync
