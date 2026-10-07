#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run from the unpacked radio update directory on the existing Debian phone.
set -eu
case "${1:-}" in
 '') bootstrap=0 ;;
 --bootstrap) bootstrap=1 ;;
 *) echo 'Usage: install.sh [--bootstrap]' >&2; exit 2 ;;
esac
[ "$(id -u)" = 0 ] || { echo 'Run with sudo' >&2; exit 1; }
[ "$(dpkg --print-architecture)" = arm64 ] || { echo 'This update is for arm64 Debian' >&2; exit 1; }
update=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$update"
sha256sum --quiet -c SHA256SUMS
if [ "$bootstrap" = 1 ]; then
 # Stage matching modules and firmware without using APT, or starting hardware.
 # The kernel release remains the same, but FILE_LOCKING changes VFS layouts.
 cp -r --no-preserve=ownership files/. /
 while IFS= read -r path; do
  if [ -e "$path" ]; then chown 0:0 "$path"; fi
 done < ownership-paths.txt
 sync
 printf '\nBootstrap staged; no packages or radio services were started.\n'
 printf 'Shut down and boot the corrected radio-disabled boot-libra-alpine-drm.img.\n'
 printf 'Then run this installer again without --bootstrap.\n'
 exit 0
fi
# Check the running kernel, rather than trusting an offline image test.
if ! python3 -c 'import fcntl,tempfile; f=tempfile.TemporaryFile(); fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB); f.close()'; then
 echo 'POSIX file locking is unavailable in the running kernel.' >&2
 echo 'Use install.sh --bootstrap, then boot the corrected radio-disabled image.' >&2
 exit 1
fi
# Refuse to run service hooks while packages are configured. Preserve user policy.
policy=/usr/sbin/policy-rc.d
if [ -e "$policy" ]; then
 echo 'Existing policy-rc.d detected; leave its service policy in place.'
else
 printf '#!/bin/sh\nexit 101\n' > "$policy"
 chmod 755 "$policy"
 created_policy=1
fi
cleanup() {
 if [ "${created_policy:-0}" = 1 ]; then rm -f "$policy"; fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
# Older overlay copies carried checkout ownership into these system paths.
# Repair only the known overlay paths, preserving user data and setuid binaries.
while IFS= read -r path; do
 if [ -e "$path" ]; then chown 0:0 "$path"; fi
done < ownership-paths.txt
# All new dependencies are bundled. No network or distribution upgrade needed.
# With --no-download, APT also expects local packages in its archive cache.
install -d -m 755 /var/cache/apt/archives
cp debs/*.deb /var/cache/apt/archives/
apt-get install -y --no-download --no-install-recommends ./debs/*.deb
# Debian's default DB signature uses a key not included in this kernel.
update-alternatives --set regulatory.db /lib/firmware/regulatory.db-upstream
cp -r --no-preserve=ownership files/. /
depmod 6.12.112+
systemctl daemon-reload
udevadm control --reload-rules
systemctl enable libra-radio.service bluetooth
cleanup
trap - EXIT
printf '\nInstalled. Shut down, then boot the matching boot-libra-alpine-drm.img.\n'
printf 'After boot: sudo libra-radio-status\n'
