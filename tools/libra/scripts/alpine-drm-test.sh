#!/bin/sh
# RAM-only DRM diagnostics and an explicit, interactive test-pattern modeset.
set -u

action=${1:-scan}
case "$action" in
	scan) [ "$#" -le 1 ] || { printf 'Usage: libra-drm-test [scan | modeset CONNECTOR CRTC]\n' >&2; exit 2; } ;;
	modeset)
		[ "$#" -eq 3 ] || { printf 'Usage: libra-drm-test modeset CONNECTOR CRTC\n' >&2; exit 2; }
		for id in "$2" "$3"; do
			case "$id" in ''|*[!0-9]*) printf 'Connector and CRTC IDs must be numeric.\n' >&2; exit 2 ;; esac
		done
		;;
	*) printf 'Usage: libra-drm-test [scan | modeset CONNECTOR CRTC]\n' >&2; exit 2 ;;
esac

output=/run/libra-drm
mkdir -p "$output" || exit 1

snapshot() {
	dmesg > "$output/dmesg-$1.txt" 2>&1
	{
		uname -a
		printf '\nBoot command line:\n'
		cat /proc/cmdline
		printf '\nDRM devices:\n'
		ls -l /dev/dri
		printf '\nConnector state:\n'
		for property in /sys/class/drm/card*-*/status /sys/class/drm/card*-*/modes /sys/class/drm/card*-*/enabled; do
			[ -r "$property" ] || continue
			printf '\n%s:\n' "$property"
			cat "$property"
		done
		printf '\nDeferred probes:\n'
		[ ! -r /sys/kernel/debug/devices_deferred ] || cat /sys/kernel/debug/devices_deferred
		printf '\nDRM atomic state:\n'
		for state in /sys/kernel/debug/dri/*/state; do
			[ ! -r "$state" ] || cat "$state"
		done
		printf '\nBacklight state:\n'
		for property in /sys/class/backlight/*/brightness /sys/class/backlight/*/actual_brightness /sys/class/backlight/*/max_brightness /sys/class/backlight/*/bl_power; do
			[ -r "$property" ] || continue
			printf '%s: ' "$property"
			cat "$property"
		done
		printf '\nInterrupt counts:\n'
		cat /proc/interrupts
	} > "$output/state-$1.txt" 2>&1
	for summary in clk/clk_summary regulator/regulator_summary gpio; do
		[ -r "/sys/kernel/debug/$summary" ] || continue
		cat "/sys/kernel/debug/$summary" > "$output/${summary##*/}-$1.txt" 2>&1
	done
}

snapshot before
if [ "$action" = scan ]; then
	modetest -M msm -c -e -p > "$output/modetest-scan.txt" 2>&1
	result=$?
	cat "$output/modetest-scan.txt"
else
	printf 'Testing 1080x1920 at 60 Hz on connector %s, CRTC %s.\n' "$2" "$3"
	printf 'Check the screen for a test pattern; press Enter to finish.\n'
	trap 'snapshot interrupted; exit 130' INT TERM HUP
	modetest -M msm -s "$2@$3:1080x1920-60" > "$output/modetest-modeset.txt" 2>&1
	result=$?
	trap - INT TERM HUP
	cat "$output/modetest-modeset.txt"
fi
snapshot after
printf '\nmodetest exit status: %s\nLogs: %s\n' "$result" "$output"
printf '\nRecent display messages:\n'
dmesg | grep -Ei 'drm|mdp|mdss|dsi|pll|panel|wled|lab|ibb|defer' | tail -n 40 || :
exit "$result"
