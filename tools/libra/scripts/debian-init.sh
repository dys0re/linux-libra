#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Tiny RAM init: identify userdata, expand its prepared F2FS, then run systemd.
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts /run /tmp /newroot /sys/kernel/config /sys/kernel/debug
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /run
mount -t tmpfs tmpfs /tmp
mount -t configfs configfs /sys/kernel/config
mount -t debugfs debugfs /sys/kernel/debug
ip link set lo up
# Keep a rescue shell available while storage probes, even if userdata is absent.
(
 trap 'kill "$serial_pid" 2>/dev/null; exit' TERM
 while :; do
  if [ -c /dev/ttyGS0 ]; then
   setsid getty -L -n -l /bin/sh 115200 ttyGS0 vt100 &
   serial_pid=$!
   wait "$serial_pid"
  else sleep 1; fi
 done
) > /run/libra-initrd-acm.log 2>&1 &
acm_pid=$!
/usr/sbin/libra-usb-gadget > /run/libra-usb.log 2>&1 &
usb_pid=$!
rescue() {
 printf '\nDebian root startup failed: %s\nUSB serial rescue shell remains available.\n' "$*"
 while :; do setsid getty -L -n -l /bin/sh 115200 tty1 linux; sleep 1; done
}
root_device=''
elapsed=0
while [ -z "$root_device" ]; do
 for path in /sys/class/block/*; do
  [ -r "$path/uevent" ] || continue
  if grep -qx 'PARTNAME=userdata' "$path/uevent"; then
   root_device="/dev/${path##*/}"
   break
  fi
 done
 [ -z "$root_device" ] || break
 [ "$elapsed" -lt 60 ] || rescue 'GPT partition userdata was not found'
 sleep 1
 elapsed=$((elapsed + 1))
done
case "$(blkid "$root_device")" in
 *'LABEL="libra-debian"'*'TYPE="f2fs"'*) ;;
 *) rescue "$root_device is not the prepared libra-debian F2FS root" ;;
esac
mount -t f2fs -o ro "$root_device" /newroot || rescue 'initial root mount failed'
[ -x /newroot/sbin/init ] || rescue 'systemd /sbin/init is missing'
if [ ! -e /newroot/etc/libra/rootfs-expanded ]; then
 umount /newroot || rescue 'cannot unmount root before expansion'
 resize.f2fs "$root_device" > /run/libra-resize.log 2>&1 || rescue 'F2FS expansion failed; see /run/libra-resize.log'
 mount -t f2fs -o rw,noatime "$root_device" /newroot || rescue 'expanded root mount failed'
 mkdir -p /newroot/etc/libra
 touch /newroot/etc/libra/rootfs-expanded
else
 mount -o remount,rw,noatime /newroot || rescue 'root remount failed'
fi
wait "$usb_pid" || true
# Getty and its login child must release the initrd before switch_root.
kill "$acm_pid" 2>/dev/null || true
wait "$acm_pid" 2>/dev/null || true
for path in dev proc sys run; do
 mkdir -p "/newroot/$path"
 mount --move "/$path" "/newroot/$path" || rescue "moving $path failed"
done
exec switch_root /newroot /sbin/init
