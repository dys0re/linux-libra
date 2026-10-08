#!/bin/sh
# Start the native framebuffer console after USB configuration completes.
set -eu

gpu_desktop=0
if [ -f /etc/libra/gpu-desktop ] && [ "$(cat /etc/libra/gpu-desktop)" = 1 ]; then
	gpu_desktop=1
fi
# Leave the firmware framebuffer untouched when desktop GPU mode is disabled.
if [ "$gpu_desktop" -eq 0 ] && grep -qw 'libra.gpu_defer=1' /proc/cmdline; then
	printf 'Native DRM deferred for the manual first-load GPU test; USB/SSH remain available.\n'
	exit 0
fi

blackout() {
	for brightness in /sys/class/backlight/*/brightness; do
		[ ! -w "$brightness" ] || printf '0\n' > "$brightness" || :
	done
}
ready=0
trap '[ "$ready" -eq 1 ] || blackout' EXIT
trap 'exit 130' INT TERM HUP

# Do not block PID 1 or the ACM getty while providers finish probing.
# USB gadget success is written only after UDC binding and network setup.
elapsed=0
while [ ! -f /run/libra-usb-ready ]; do
	if [ "$elapsed" -ge 60 ]; then
		printf 'USB setup did not complete; native console loading was skipped.\n' >&2
		exit 1
	fi
	sleep 1
	elapsed=$((elapsed + 1))
done

if [ "$gpu_desktop" -eq 1 ]; then
	/usr/sbin/libra-gpu-prepare
	export LIBRA_GPU=1
fi

for stage in bias backlight panel release console; do
	/usr/sbin/libra-drm-load "$stage"
done
printf 'Native DRM console ready.\n' > /dev/tty1
/usr/sbin/libra-drm-test console
ready=1
printf 'Native DRM console is ready; USB ACM remains available.\n'
