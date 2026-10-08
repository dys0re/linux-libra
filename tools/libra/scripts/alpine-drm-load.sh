#!/bin/sh
# Load exactly one native-display stage through the existing USB shell.
set -eu
stage=${1:-}
case "$stage" in
	bias) module=qcom_labibb_regulator ;;
	backlight) module=qcom_wled ;;
	panel) module=panel_sharp_libra_rsp61322 ;;
	release) module=framebuffer ;;
	msm|console) module=msm ;;
	*) printf 'Usage: libra-drm-load bias|backlight|panel|release|msm|console\n' >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { printf 'Specify exactly one stage.\n' >&2; exit 2; }
if ! grep -qw 'libra.drm_native=1' /proc/cmdline; then
	printf 'Use the native-DRM image; this command does not enable disabled DT nodes.\n' >&2
	exit 1
fi
backlight_bound() {
	for device in /sys/class/backlight/*; do
		[ -L "$device/device/driver/module" ] || continue
		[ "$(basename "$(readlink "$device/device/driver/module")")" != qcom_wled ] || return 0
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

framebuffer_bound() {
	for device in /sys/bus/platform/drivers/simple-framebuffer/*; do
		[ ! -L "$device/driver" ] || return 0
	done
	return 1
}

blackout() {
	for brightness in /sys/class/backlight/*/brightness; do
		[ -w "$brightness" ] || continue
		printf '0' > "$brightness" || :
	done
}

# Keep the backlight off until native scanout has been checked.
if [ "$module" = msm ] || [ "$stage" = release ]; then
	blackout
fi

if [ -d "/sys/module/$module" ]; then
	printf '%s is already loaded.\n' "$module"
	if [ "$stage" = backlight ] && ! backlight_bound; then
		printf 'WLED module is present, but no bound WLED backlight exists.\n' >&2
		exit 1
	fi
	if [ "$module" = msm ] && ! native_drm_bound; then
		printf 'MSM module is present, but the native DRM device has not bound.\n' >&2
		exit 1
	fi
	if [ "$stage" = console ]; then
		case "$(cat /sys/module/msm/parameters/fbdev)" in
			Y|1) ;;
			*) printf 'MSM was loaded without fbdev; reboot before enabling the native console.\n' >&2; exit 1 ;;
		esac
	fi
	exit 0
fi
if [ "$module" = msm ]; then
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
		printf 'Release simpledrm before loading MSM so its PLL parents can register without active orphan-clock references.\n' >&2
		exit 1
	fi
fi

if [ "$stage" = release ] && [ -d /sys/module/msm ]; then
	printf 'MSM is already loaded; firmware release must precede native driver registration.\n' >&2
	exit 1
fi

output=/run/libra-drm-load
mkdir -p "$output"
printf '\n=== DRM load stage: %s (%s) ===\n' "$stage" "$module"
if [ -c /dev/pmsg0 ]; then
	printf 'libra DRM: beginning stage %s\n' "$stage" > /dev/pmsg0 || :
fi
if [ "$stage" = release ]; then
	printf 'Releasing the simpledrm firmware framebuffer...\n'
	if /usr/sbin/libra-kmsg "$output/$stage-live.txt" /bin/sh -ec '
		for device in /sys/bus/platform/drivers/simple-framebuffer/*; do
			[ -L "$device/driver" ] || continue
			printf "Unbinding %s...\n" "${device##*/}"
			printf "%s" "${device##*/}" > /sys/bus/platform/drivers/simple-framebuffer/unbind
		done
		sleep 1
	'; then result=0; else result=$?; fi
	if [ "$result" -eq 0 ] && framebuffer_bound; then
		printf 'Firmware framebuffer is still bound; refusing native handover.\n' >&2
		result=1
	fi
elif [ "$module" = msm ]; then
	gpu=${LIBRA_GPU:-0}
	case "$gpu" in 0|1) ;; *) printf 'LIBRA_GPU must be 0 or 1.\n' >&2; exit 2;; esac
	fbdev=0
	[ "$stage" != console ] || fbdev=1
	printf 'Registering native MSM/DSI/PHY drivers (fbdev=%s)...\n' "$fbdev"
	# Keep capture active briefly after modprobe for deferred probe workers.
	if /usr/sbin/libra-kmsg "$output/$stage-live.txt" /bin/sh -c '
		/sbin/modprobe msm "fbdev=$1" "gpu=$2" mdp5_core_clk_rate=200000000
		result=$?
		sleep 1
		exit "$result"
	' sh "$fbdev" "$gpu"; then result=0; else result=$?; fi
else
	printf 'Loading %s...\n' "$module"
	set -- "$module"
	if [ "$stage" = panel ] && framebuffer_bound; then
		printf 'Requesting OEM firmware-panel preservation for the handover.\n'
		set -- "$module" firmware_handoff=1
	fi
	if /usr/sbin/libra-kmsg "$output/$stage-live.txt" /sbin/modprobe "$@"; then
		result=0
	else
		result=$?
	fi
fi
if [ "$result" -eq 0 ] && grep -Eq 'WARNING:|Internal error:|BUG:|Kernel panic|Unbalanced enable for IRQ|invalid sysfs_emit|wait for video done timed out|cmd dma tx failed|panel shutdown command failed|DSI RCG input clock|DSI PLL .*timeout|DSI PLL failed to lock|failed to enable link clocks|DSI (timeout|FIFO) status=|dsi_err_worker: status=|panel bias output not ready:|libra_panel_prepare.*failed:|Power on failed:|flip_done timed out|commit wait timed out' "$output/$stage-live.txt"; then
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
if [ "$module" = msm ] && [ "$result" -eq 0 ]; then
	if native_drm_bound; then
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
printf '\nStage %s returned %s.\n' "$stage" "$result"
printf 'Logs: %s\n' "$output"
exit "$result"
