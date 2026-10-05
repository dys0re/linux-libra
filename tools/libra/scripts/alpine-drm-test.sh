#!/bin/sh
# RAM-only DRM diagnostics and explicit interactive/timed test-pattern modesets.
set -u

action=${1:-scan}
wake_mode=''
case "$action" in
	wake-lp|wake-hs) wake_mode=${action#wake-}; action=preview ;;
esac
case "$action" in
	scan|backlight) [ "$#" -le 1 ] || { printf 'Usage: libra-drm-test [scan | backlight | modeset CONNECTOR CRTC | hold CONNECTOR CRTC | preview CONNECTOR CRTC | wake-lp CONNECTOR CRTC | wake-hs CONNECTOR CRTC | dsi-pattern CONNECTOR CRTC]\n' >&2; exit 2; } ;;
	modeset|hold|preview|dsi-pattern)
		[ "$#" -eq 3 ] || { printf 'Usage: libra-drm-test %s CONNECTOR CRTC\n' "$action" >&2; exit 2; }
		for id in "$2" "$3"; do
			case "$id" in ''|*[!0-9]*) printf 'Connector and CRTC IDs must be numeric.\n' >&2; exit 2 ;; esac
		done
		;;
	*) printf 'Usage: libra-drm-test [scan | backlight | modeset CONNECTOR CRTC | hold CONNECTOR CRTC | preview CONNECTOR CRTC | wake-lp CONNECTOR CRTC | wake-hs CONNECTOR CRTC | dsi-pattern CONNECTOR CRTC]\n' >&2; exit 2 ;;
esac

output=/run/libra-drm
mkdir -p "$output" || exit 1
failure_pattern='DSI PLL .*timeout|DSI PLL failed to lock|DSI (timeout|FIFO) status=|dsi_err_worker: status=|libra_panel_prepare.*failed:|panel bias output not ready:|panel power-mode (read failed|not ready)|Power on failed:|failed to enable link clocks|vblank time out|flip_done timed out|commit wait timed out|Internal error:|synchronous external abort|errors: [0-9a-fA-F]+|WARNING:|Unbalanced enable for IRQ|BUG:|Kernel panic|wled.*failed|WLED.*(failed|fault)'

pattern_control=''
panel_power_control=''
wake_control=''
preview_brightness=64
# Match the independently observed WLED illumination level for native pixels.
[ "$action" != preview ] || preview_brightness=512

blackout() {
	for b in /sys/class/backlight/*/brightness; do
		[ ! -w "$b" ] || printf '0\n' > "$b"
	done
	if [ -n "$pattern_control" ] && [ -w "$pattern_control" ]; then
		printf '0\n' > "$pattern_control" || :
	fi
}

if [ "$action" = dsi-pattern ]; then
 for control in /sys/bus/platform/devices/*/test_pattern; do
  [ -w "$control" ] || continue
  [ -L "${control%/test_pattern}/driver/module" ] || continue
  [ "$(basename "$(readlink "${control%/test_pattern}/driver/module")")" = msm ] || continue
  pattern_control="$control"
  break
 done
 if [ -z "$pattern_control" ]; then
  printf 'No native DSI test-pattern control is available.\n' >&2
  exit 1
 fi
fi

if [ -n "$wake_mode" ]; then
	for control in /sys/bus/mipi-dsi/devices/*/power_mode; do
		[ -r "$control" ] || continue
		[ -L "${control%/power_mode}/driver/module" ] || continue
		[ "$(basename "$(readlink "${control%/power_mode}/driver/module")")" = panel_sharp_libra_rsp61322 ] || continue
		panel_power_control="$control"
		break
	done
	if [ -z "$panel_power_control" ]; then
		printf 'Preview requires the panel power-mode diagnostic enabled at module load.\n' >&2
		blackout
		exit 1
	fi
	wake_control="${panel_power_control%/power_mode}/wake_test"
	if [ ! -w "$wake_control" ]; then
		printf 'Panel wake-test control is unavailable.\n' >&2
		blackout
		exit 1
	fi
fi

if [ "$action" = preview ] || [ "$action" = dsi-pattern ] || [ "$action" = backlight ]; then
	preview_backlight=''
	for b in /sys/class/backlight/*; do
		[ -L "$b/device/driver/module" ] || continue
		[ "$(basename "$(readlink "$b/device/driver/module")")" = qcom_wled ] || continue
		preview_backlight="$b"
		break
	done
	if [ -z "$preview_backlight" ]; then
		printf 'No bound WLED backlight for preview.\n' >&2
		exit 1
	fi
	if [ -r "$preview_backlight/device/firmware_state" ]; then
		if ! cat "$preview_backlight/device/firmware_state" > "$output/preview-firmware-check.txt" ||
		   [ ! -s "$output/preview-firmware-check.txt" ]; then
			printf 'Firmware WLED snapshot is unavailable; skip preview until diagnostics are fixed.\n' >&2
			blackout
			exit 1
		fi
	fi
	blackout
fi

# Isolate the LED boost/current path before native display initialization.
# Sysfs readback verifies programming only; observe physical light separately.
if [ "$action" = backlight ]; then
	if [ -d /sys/module/msm ]; then
		printf 'Run the isolated backlight test before libra-drm-load msm.\n' >&2
		exit 1
	fi
	trap blackout EXIT
	trap 'exit 130' INT TERM HUP
	dmesg > "$output/backlight-before.txt"
	printf 'Isolated WLED test: brightness 512/4095 for 3 seconds; finish is automatic.\n'
	if [ "$(cat "$preview_backlight/max_brightness")" != 4095 ] ||
	   ! printf '512\n' > "$preview_backlight/brightness"; then
		exit 1
	fi
	sleep 1
	{
		for field in brightness actual_brightness bl_power max_brightness; do
			printf '%s=' "$field"
			cat "$preview_backlight/$field"
		done
		cat "$preview_backlight/device/hardware_state"
	} > "$output/backlight-live.txt" 2>&1
	cat "$output/backlight-live.txt"
	sleep 2
	blackout
	dmesg > "$output/backlight-after.txt"
	before_lines=$(wc -l < "$output/backlight-before.txt")
	now_lines=$(wc -l < "$output/backlight-after.txt")
	if [ "$now_lines" -ge "$before_lines" ]; then
		tail -n "+$((before_lines + 1))" "$output/backlight-after.txt" > "$output/backlight-new.txt"
	else
		cp "$output/backlight-after.txt" "$output/backlight-new.txt"
	fi
	result=0
	if ! grep -qx 'actual_brightness=512' "$output/backlight-live.txt" ||
	   ! grep -qx 'd846: 80' "$output/backlight-live.txt" ||
	   grep -Eq "$failure_pattern" "$output/backlight-new.txt" ||
	   [ "$(cat "$preview_backlight/actual_brightness")" != 0 ]; then
		printf 'WLED programming or cleanup failed.\n' >&2
		result=1
	fi
	cat "$output/backlight-new.txt"
	printf 'WLED programming test exit status: %s; physical illumination must be observed.\nLogs: %s\n' "$result" "$output"
	exit "$result"
fi

drm_states() {
	seen_states=''
	for state in /sys/kernel/debug/dri/*/state; do
		[ -r "$state" ] || continue
		resolved=$(readlink -f "$state") || continue
		# Numeric minors and the device directory can alias the same state.
		case " $seen_states " in *" $resolved "*) continue ;; esac
		seen_states="$seen_states $resolved"
		printf '\nDRM state: %s\n' "$resolved"
		cat "$resolved"
	done
}

live_summary() {
	awk -v id="$2" -v sample="$1" '
		/^plane\[/ { section = "plane"; plane_crtc = "" }
		/^crtc\[/ {
			section = "crtc"
			target = ($0 ~ ("^crtc\\[" id "\\]:"))
			if (target) { name = $0; sub(/^.*\]: /, "", name); found = 1 }
		}
		/^connector\[/ { section = "connector"; target = 0 }
		section == "plane" && /^[[:space:]]*crtc=/ {
			plane_crtc = $0; sub(/^[[:space:]]*crtc=/, "", plane_crtc)
		}
		section == "plane" && /^[[:space:]]*fb=[1-9][0-9]*$/ { buffers[plane_crtc] = 1 }
		section == "crtc" && target && /^[[:space:]]*active=/ {
			active = $0; sub(/^[[:space:]]*active=/, "", active)
		}
		section == "crtc" && target && /^[[:space:]]*underrun_count=/ {
			count = $0; sub(/^[[:space:]]*underrun_count=/, "", count); have_count = 1
		}
		section == "crtc" && target && /^[[:space:]]*intf_frame_count=/ {
			frames = $0; sub(/^[[:space:]]*intf_frame_count=/, "", frames); have_frames = 1
		}
		END {
			valid = found && active == 1 && buffers[name] && have_count && have_frames
			printf "%s: CRTC %s active=%s framebuffer_present=%d underrun_count=%s frame_count=%s valid=%d\n",
			       sample, id, found ? active : "missing", buffers[name] ? 1 : 0,
			       have_count ? count : "missing", have_frames ? frames : "unavailable", valid ? 1 : 0
			exit !valid
		}
	' "$output/state-live-$1.txt"
}

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
		drm_states
		printf '\nBacklight state:\n'
		for property in /sys/class/backlight/*/brightness /sys/class/backlight/*/actual_brightness /sys/class/backlight/*/max_brightness /sys/class/backlight/*/bl_power; do
			[ -r "$property" ] || continue
			printf '%s: ' "$property"
			cat "$property"
		done
		for b in /sys/class/backlight/*; do
			for field in firmware_state hardware_state; do
				[ -r "$b/device/$field" ] || continue
				printf '\nWLED %s:\n' "$field"
				cat "$b/device/$field"
			done
		done
		printf '\nInterrupt counts:\n'
		cat /proc/interrupts
		printf '\nUSB and network state:\n'
		ls /sys/class/udc
		for state in /sys/class/udc/*/state; do
			[ -r "$state" ] || continue
			printf '%s: ' "$state"
			cat "$state"
		done
		ip addr
		ip -s link
		printf '\nUSB setup log:\n'
		[ ! -r /run/libra-usb.log ] || cat /run/libra-usb.log
	} > "$output/state-$1.txt" 2>&1
	# clk_summary runtime-resumes every clock provider. Read only the plain
	# software counters; clk_rate and clk_parent can also invoke callbacks.
	{
		for clock in /sys/kernel/debug/clk/*; do
			[ -d "$clock" ] || continue
			for field in clk_prepare_count clk_enable_count; do
				[ -r "$clock/$field" ] || continue
				printf '%s %s: ' "${clock##*/}" "$field"
				cat "$clock/$field"
			done
		done
	} > "$output/clk-counts-$1.txt" 2>&1
	for summary in regulator/regulator_summary gpio; do
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
	rm -f "$output/state-live-2s.txt" "$output/state-live-5s.txt" \
		"$output/live-summary-2s.txt" "$output/live-summary-5s.txt" \
		"$output/preview-ready.txt" "$output/preview-backlight.txt"
	rm -f "$output/panel-power-live.txt"
	printf 'Testing 1080x1920 at 60 Hz on connector %s, CRTC %s.\n' "$2" "$3"
	if [ -n "$wake_mode" ]; then
		printf 'Explicit wake test: one Sleep Out in %s mode after live scanout is ready.\n' "$wake_mode"
	fi
	if [ "$action" = hold ] || [ "$action" = preview ] || [ "$action" = dsi-pattern ]; then
		printf 'Holding the test pattern for 8 seconds; finish is automatic.\n'
	else
		printf 'Keep the test pattern active for at least 5 seconds; press Enter to finish.\n'
	fi
	trap 'blackout; snapshot interrupted; exit 130' INT TERM HUP
	# Passive CRTC state/counters while the test framebuffer is still active.
	# Buffer monitor output: ACM backpressure must not delay the 5 s sample
	# until after the test framebuffer has been removed at 8 s.
	(
		if [ "$action" = preview ] || [ "$action" = dsi-pattern ]; then
			trap blackout EXIT
			trap 'exit 1' INT TERM HUP
		fi
		sleep 2
		for sample in 2s 5s; do
			{
				cat /proc/uptime
				drm_states
				cat /proc/interrupts
			} > "$output/state-live-$sample.txt" 2>&1
			if { [ "$action" = preview ] || [ "$action" = dsi-pattern ]; } && [ "$sample" = 2s ]; then
				if ! live_summary 2s "$3" > "$output/preview-ready.txt" ||
				   ! grep -q 'underrun_count=0 ' "$output/preview-ready.txt"; then
					printf 'Preview skipped: live scanout is not ready.\n' >&2
					exit 1
				fi
				if [ -n "$wake_mode" ] && ! printf '%s\n' "$wake_mode" > "$wake_control"; then
					printf 'Preview skipped: explicit %s wake test failed; inspect power-mode replies.\n' "$wake_mode" >&2
					exit 1
				fi
				if [ -n "$wake_mode" ]; then
					if ! cat "$panel_power_control" > "$output/panel-power-live.txt"; then
						printf 'Preview skipped: active panel power-mode read failed.\n' >&2
						exit 1
					fi
					printf 'Active panel power mode: '
					cat "$output/panel-power-live.txt"
					if ! grep -q 'display_on=1 sleep_out=1' "$output/panel-power-live.txt"; then
						printf 'Preview skipped: panel is not awake with video running.\n' >&2
						exit 1
					fi
				fi
				dmesg > "$output/preview-kmsg.txt"
				before_lines=$(wc -l < "$output/dmesg-before.txt")
				now_lines=$(wc -l < "$output/preview-kmsg.txt")
				if [ "$now_lines" -ge "$before_lines" ]; then
					tail -n "+$((before_lines + 1))" "$output/preview-kmsg.txt" > "$output/preview-kmsg-new.txt"
				else
					cp "$output/preview-kmsg.txt" "$output/preview-kmsg-new.txt"
				fi
				if grep -Eq "$failure_pattern" "$output/preview-kmsg-new.txt"; then
					printf 'Preview skipped: kernel warning or display error.\n' >&2
					exit 1
				fi
				if [ "$action" = dsi-pattern ]; then
					printf '1\n' > "$pattern_control" || exit 1
					if [ "$(cat "$pattern_control")" != 1 ]; then
						printf 'DSI checkerboard enable did not read back.\n' >&2
						exit 1
					fi
					printf 'Pixel source: DSI host checkerboard; MDP scanout pixels bypassed.\n'
				fi
				printf '%s\n' "$preview_brightness" > "$preview_backlight/brightness" || exit 1
				{
					printf 'Preview backlight: %s\n' "$preview_backlight"
					for field in brightness actual_brightness bl_power max_brightness; do
						printf '%s=' "$field"
						cat "$preview_backlight/$field"
					done
					for field in firmware_state hardware_state; do
						[ -r "$preview_backlight/device/$field" ] || continue
						printf '\nWLED %s:\n' "$field"
						cat "$preview_backlight/device/$field"
						done
				} > "$output/preview-backlight.txt" 2>&1
				cat "$output/preview-backlight.txt"
				if ! grep -qx "actual_brightness=$preview_brightness" "$output/preview-backlight.txt"; then
					printf 'Preview brightness readback does not match %s; turning backlight off.\n' "$preview_brightness" >&2
					exit 1
				fi
			fi
			[ "$sample" != 2s ] || sleep 3
		done
	) > "$output/monitor.txt" 2>&1 &
	monitor_pid=$!
	if [ "$action" = hold ] || [ "$action" = preview ] || [ "$action" = dsi-pattern ]; then
		# Ignore queued serial newlines/EOF; feed one newline only after 8 s.
		(sleep 8; printf '\n') | modetest -M msm -s "$2@$3:1080x1920-60" > "$output/modetest-modeset.txt" 2>&1
		result=$?
	else
		modetest -M msm -s "$2@$3:1080x1920-60" > "$output/modetest-modeset.txt" 2>&1
		result=$?
	fi
	if ! wait "$monitor_pid"; then
		if [ "$result" -eq 0 ]; then result=1; fi
	fi
	trap - INT TERM HUP
	cat "$output/monitor.txt"
	cat "$output/modetest-modeset.txt"
	printf '\nLive scanout samples:\n'
	valid_samples=1
	for sample in 2s 5s; do
		if [ ! -s "$output/state-live-$sample.txt" ]; then
			printf '%s: sample not taken; monitor stopped early.\n' "$sample"
			valid_samples=0
			if [ "$result" -eq 0 ]; then result=1; fi
			continue
		fi
		if ! live_summary "$sample" "$3" > "$output/live-summary-$sample.txt"; then
			valid_samples=0
			printf 'Invalid live sample: active CRTC, attached framebuffer and frame counter are required.\n' >&2
			if [ "$result" -eq 0 ]; then result=1; fi
		fi
		cat "$output/live-summary-$sample.txt"
	done
	frames_before=''
	frames_after=''
	if [ "$valid_samples" -eq 1 ]; then
		frames_before=$(sed -n 's/.* frame_count=\([0-9][0-9]*\) .*/\1/p' "$output/live-summary-2s.txt")
		frames_after=$(sed -n 's/.* frame_count=\([0-9][0-9]*\) .*/\1/p' "$output/live-summary-5s.txt")
	fi
	if [ "$valid_samples" -eq 1 ] && [ -n "$frames_before" ] && [ -n "$frames_after" ]; then
		frame_delta=$(( (frames_after - frames_before + 4294967296) % 4294967296 ))
		printf 'Hardware frame progress between samples: %s frames\n' "$frame_delta"
		if [ "$frame_delta" -eq 0 ]; then
			printf 'Hardware frame counter did not advance; keep backlight off.\n' >&2
			if [ "$result" -eq 0 ]; then result=1; fi
		fi
	fi
fi
snapshot after
before_lines=$(wc -l < "$output/dmesg-before.txt")
after_lines=$(wc -l < "$output/dmesg-after.txt")
if [ "$after_lines" -ge "$before_lines" ]; then
	tail -n "+$((before_lines + 1))" "$output/dmesg-after.txt" > "$output/dmesg-new.txt"
else
	# The ring wrapped; preserve the available records instead of losing errors.
	cp "$output/dmesg-after.txt" "$output/dmesg-new.txt"
fi
if [ "$action" != scan ] && grep -Eq "$failure_pattern" "$output/dmesg-new.txt"; then
	blackout
	printf '\nKernel display failure detected; keep backlight off.\n' >&2
	if [ "$result" -eq 0 ]; then result=1; fi
fi
printf '\nDRM test exit status: %s\nLogs: %s\n' "$result" "$output"
printf '\nRecent display messages:\n'
dmesg | grep -Ei 'drm|mdp|mdss|dsi|pll|panel|wled|lab|ibb|defer' | tail -n 40 || :
exit "$result"
