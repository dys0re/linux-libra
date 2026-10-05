#!/bin/sh
# Load exactly one native-display stage through the existing USB shell.
set -eu
stage=${1:-}
case "$stage" in
	bias) module=qcom_labibb_regulator ;;
	backlight) module=qcom_wled ;;
	panel) module=panel_sharp_libra_rsp61322 ;;
	msm) module=msm ;;
	release) module=framebuffer ;;
	*) printf 'Usage: libra-drm-load bias|backlight|panel|release|msm\n' >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { printf 'Specify exactly one stage.\n' >&2; exit 2; }
if ! grep -qw 'libra.drm_late=1' /proc/cmdline; then
	printf 'Use the deferred-DRM image; this command does not enable disabled DT nodes.\n' >&2
	exit 1
fi
backlight_bound() {
	for device in /sys/class/backlight/*; do
		[ -L "$device/device/driver/module" ] || continue
		[ "$(basename "$(readlink "$device/device/driver/module")")" != qcom_wled ] || return 0
	done
	return 1
}

framebuffer_bound() {
	for device in /sys/bus/platform/drivers/simple-framebuffer/*; do
		[ ! -L "$device/driver" ] || return 0
	done
	return 1
}

native_drm_bound() {
	for device in /sys/class/drm/card[0-9]*; do
		[ -L "$device/device/driver/module" ] || continue
		[ "$(basename "$(readlink "$device/device/driver/module")")" != msm ] || return 0
	done
	return 1
}

blackout() {
	for brightness in /sys/class/backlight/*/brightness; do
		[ -w "$brightness" ] || continue
		printf '0' > "$brightness" || :
	done
}

kernel_faulted() {
	bits=''
	if [ -r /proc/sys/kernel/tainted ]; then
		bits=$(cat /proc/sys/kernel/tainted) || bits=''
	fi
	case "$bits" in
		''|*[!0-9]*)
			messages=$(dmesg) || return 0
			printf '%s\n' "$messages" | grep -Eq 'Internal error:|synchronous external abort|Kernel panic|BUG:'
			return $?
			;;
	esac
	# MACHINE_CHECK (4) and DIE/OOPS (7) can arise in deferred probe workers.
	[ "$((bits & 144))" -ne 0 ]
}

if kernel_faulted; then
	blackout
	printf 'Kernel has a machine check/Oops; reboot before further DRM operations.\n' >&2
	exit 1
fi

# This image tests controller probe with the LCD backlight kept off.
if [ "$stage" = release ] || [ "$stage" = msm ]; then
	blackout
fi

if [ -d "/sys/module/$module" ]; then
	printf '%s is already loaded.\n' "$module"
	if [ "$stage" = backlight ] && ! backlight_bound; then
		printf 'WLED module is present, but no bound WLED backlight exists.\n' >&2
		exit 1
	fi
	if [ "$stage" = msm ] && ! native_drm_bound; then
		printf 'MSM module is present, but the native DRM device has not bound.\n' >&2
		exit 1
	fi
	exit 0
fi
if [ "$stage" = msm ]; then
	for required in qcom_labibb_regulator qcom_wled panel_sharp_libra_rsp61322; do
		if [ ! -d "/sys/module/$required" ]; then
			printf 'Load bias, backlight and panel stages before msm (missing %s).\n' "$required" >&2
			exit 1
		fi
	done
	if ! backlight_bound; then
		printf 'WLED has not bound; fix backlight before native MSM probe.\n' >&2
		exit 1
	fi
	if framebuffer_bound; then
		printf 'Run libra-drm-load release first, then check USB before loading msm.\n' >&2
		exit 1
	fi
fi
if [ "$stage" = release ] && [ -d /sys/module/msm ]; then
	printf 'MSM is already loaded; reboot before testing framebuffer release.\n' >&2
	exit 1
fi

output=/run/libra-drm-load
mkdir -p "$output"
dmesg > "$output/$stage-before.txt"
printf '\n=== DRM load stage: %s (%s) ===\n' "$stage" "$module"
printf 'Keep the host serial transcript; USB may stop during this stage.\n'
if [ -c /dev/pmsg0 ]; then
	printf 'libra DRM: beginning stage %s\n' "$stage" > /dev/pmsg0 || :
fi
if [ "$stage" = release ]; then
	# Drop simpledrm's prepared DSI clocks before orphan parents reconnect
	# to the new PLL provider. This stage does not register native drivers.
	printf 'Releasing the firmware framebuffer only...\n'
	if /usr/sbin/libra-kmsg "$output/$stage-live.txt" /bin/sh -c '
		set -e
		for device in /sys/bus/platform/drivers/simple-framebuffer/*; do
			[ -L "$device/driver" ] || continue
			printf "Unbinding %s...\n" "${device##*/}"
			printf "%s" "${device##*/}" > /sys/bus/platform/drivers/simple-framebuffer/unbind
			printf "Framebuffer unbind returned.\n"
		done
	'; then result=0; else result=$?; fi
elif [ "$stage" = msm ]; then
	printf 'Registering native MSM/DSI/PHY drivers (fbdev=0)...\n'
	# Keep capture active briefly after modprobe for deferred probe workers.
	if /usr/sbin/libra-kmsg "$output/$stage-live.txt" /bin/sh -c '
		/sbin/modprobe msm fbdev=0 mdp5_core_clk_rate=200000000
		result=$?
		sleep 1
		exit "$result"
	'; then result=0; else result=$?; fi
else
	printf 'Loading %s...\n' "$module"
	if /usr/sbin/libra-kmsg "$output/$stage-live.txt" /sbin/modprobe "$module"; then result=0; else result=$?; fi
fi
dmesg > "$output/$stage-after.txt"
if [ "$result" -eq 0 ] && grep -Eq 'WARNING:|Internal error:|BUG:|Kernel panic|Unbalanced enable for IRQ|invalid sysfs_emit' "$output/$stage-live.txt"; then
	printf 'Kernel warning/error during stage %s; keep backlight off.\n' "$stage" >&2
	result=1
fi
if [ "$result" -eq 0 ] && [ "$stage" = backlight ]; then
	if backlight_bound; then
		blackout
		printf 'WLED backlight device is bound.\n'
	else
		printf 'Module insertion succeeded, but WLED device probe failed or deferred.\n' >&2
		result=1
	fi
fi
if [ "$stage" = msm ] && [ "$result" -eq 0 ]; then
	if kernel_faulted; then
		printf 'MSM deferred probe faulted despite successful module insertion.\n' >&2
		result=1
	elif native_drm_bound; then
		printf 'Native MSM DRM device is bound.\n'
	else
		printf 'MSM module loaded, but native DRM is absent; inspect probe/deferred messages.\n' >&2
		result=1
	fi
fi
if [ "$result" -ne 0 ]; then
	blackout
fi
if [ -c /dev/pmsg0 ]; then
	printf 'libra DRM: stage %s returned %s\n' "$stage" "$result" > /dev/pmsg0 || :
fi
printf '\nStage %s returned %s. Recheck host ping and ACM before continuing.\n' "$stage" "$result"
printf 'Logs: %s; no modeset has been requested.\n' "$output"
exit "$result"
