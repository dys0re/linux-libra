#!/bin/sh
# Minimal, RAM-only bring-up init. Never mount or write the phone's eMMC.
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export TERM=linux
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts /run /tmp /sys/kernel/config /sys/kernel/debug /sys/fs/pstore
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /run
mount -t tmpfs tmpfs /tmp
mount -t configfs configfs /sys/kernel/config
mount -t debugfs debugfs /sys/kernel/debug
mount -t pstore pstore /sys/fs/pstore
hostname libra-test
ip link set lo up
# Native display modules load after USB configuration; ACM stays independent.

# Start ACM before any screen output, DRM queries or status collection.
(
	while :; do
		if [ -c /dev/ttyGS0 ]; then
			setsid /sbin/getty -L -n -l /bin/sh 115200 ttyGS0 vt100
		else
			sleep 1
		fi
	done
) < /dev/null > /run/libra-acm-getty.log 2>&1 &

printf '\nAlpine Mi 4C native DRM initrd\n'
printf 'RAM-only, unauthenticated test shell\n'

# Run independently so a missing UDC cannot block the local diagnostic shell.
# The helper checks each setup step and prints the actual failure, not just a
# secondary "can't find device usb0" from an unconditional IP command.
(
	if /usr/sbin/libra-usb-gadget > /run/libra-usb.log 2>&1; then
		: > /run/libra-usb-ready
	fi
) &

if grep -qw 'libra.drm_auto=1' /proc/cmdline; then
	/usr/sbin/libra-drm-console > /run/libra-drm-console.log 2>&1 &
fi

{
	uname -a
	printf '\nCPU online: '
	cat /sys/devices/system/cpu/online
	printf '\nUSB device controllers:\n'
	ls /sys/class/udc
	printf '\nSMD transport at init:\n'
	for snapshot in /sys/bus/rpmsg/devices/*/smd_state; do
		[ -r "$snapshot" ] || continue
		cat "$snapshot"
	done
	printf '\nDRM connectors:\n'
	for status in /sys/class/drm/card*-*/status; do
		[ -f "$status" ] || continue
		printf '%s: ' "$status"
		cat "$status"
	done
	printf '\nStorage (not mounted):\n'
	cat /proc/partitions
} > /run/libra-status.txt 2>&1
cat /run/libra-status.txt
dmesg > /run/boot-dmesg.txt

printf '\nUSB serial (when bound): 115200 baud; see /run/libra-usb.log for USB state.\n'
printf 'After native driver loading: libra-drm-test scan; logs: /run/libra-drm/\n'
printf 'Native console: /run/libra-drm-console.log; manual stages: bias|backlight|panel|release|msm|console.\n'
printf 'All changes disappear at reboot. No login password in this test image.\n'

# Keep PID 1 alive, including after the local diagnostic shell exits.
trap ':' INT TERM HUP
while :; do
	# Alpine's BusyBox does not provide cttyhack. Getty supplies the local
	# controlling terminal without a missing-applet error every second.
	setsid /sbin/getty -L -n -l /bin/sh 115200 tty1 linux
	sleep 1
done
