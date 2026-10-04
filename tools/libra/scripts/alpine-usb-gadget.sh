#!/bin/sh
# RAM-only ACM + NCM/ECM setup. This is a diagnostic, not an SSH service.
set -eu

gadget=/sys/kernel/config/usb_gadget/libra
wait_seconds=${1:-60}
network_mode=${2:-ncm}
case "$wait_seconds" in
	''|*[!0-9]*) printf 'Usage: libra-usb-gadget [wait-seconds] [ncm|ecm]\n' >&2; exit 2 ;;
esac
case "$network_mode" in
	ncm) product_id=0x0105; protocol=NCM ;;
	ecm) product_id=0x0104; protocol=ECM ;;
	*) printf 'Usage: libra-usb-gadget [wait-seconds] [ncm|ecm]\n' >&2; exit 2 ;;
esac
ethernet="$gadget/functions/$network_mode.usb0"

diagnostics() {
	result=$?
	[ "$result" -ne 0 ] || return 0
	printf '\nUSB setup failed (exit %s); IP was not configured successfully.\n' "$result"
	printf '\nUDC devices:\n'
	ls /sys/class/udc 2>/dev/null || :
	printf '\nNetwork interfaces:\n'
	ip link 2>/dev/null || :
	printf '\nDeferred probes:\n'
	if [ -r /sys/kernel/debug/devices_deferred ]; then
		cat /sys/kernel/debug/devices_deferred
	fi
	printf '\nRPM/USB probe messages (including early failures):\n'
	dmesg | grep -Ei 'rpm|smd|smem|dwc3|hsphy|usb|defer|supplier' | tail -n 60 || :
	printf '\nRecent kernel messages:\n'
	dmesg | tail -n 80 || :
	# Leave the most useful evidence on the phone's final screen. Without a
	# working gadget there may be no keyboard or serial connection to scroll.
	printf '\n=== USB failure summary (photograph this screen) ===\n'
	printf 'RPM scaling progress:\n'
	dmesg | grep -E 'RPM clock scaling:|RPM clock scaling skipped|RPM clock scaling .*not enabled' | tail -n 4 || :
	printf 'First RPM transport error:\n'
	dmesg | grep -E 'RPM ACK timeout|RPM send failed|SMD doorbell.*failed' | head -n 1 || :
	dmesg | grep -Ei 'rpm.*(fail|error|timeout)|smd.*(doorbell|fail|error)|dwc3|hsphy|phy.*(fail|error)' | tail -n 12 || :
	printf '\nDeferred probes (last 8):\n'
	if [ -r /sys/kernel/debug/devices_deferred ]; then
		tail -n 8 /sys/kernel/debug/devices_deferred
	fi
	printf '\nSMD transport (state local/remote, FIFO head/tail):\n'
	for snapshot in /sys/bus/rpmsg/devices/*/smd_state; do
		[ -r "$snapshot" ] || continue
		cat "$snapshot" || :
	done
	printf '\nRPM interrupt counts:\n'
	grep -E 'smd-edge|rpm' /proc/interrupts || :
	controllers=$(ls /sys/class/udc 2>/dev/null) || controllers=''
	printf '\nUDC: %s\nLog: /run/libra-usb.log\n' "${controllers:-<none>}"
}
trap diagnostics EXIT

if [ ! -d /sys/kernel/config/usb_gadget ]; then
	printf 'USB configfs is unavailable; check its mount and kernel configuration.\n' >&2
	exit 1
fi

mkdir -p "$gadget"
if [ -z "$(cat "$gadget/UDC")" ]; then
	printf '0x1d6b' > "$gadget/idVendor"
	printf '%s' "$product_id" > "$gadget/idProduct"
	printf '0x0200' > "$gadget/bcdUSB"
	# Composite device with an IAD for each ACM/NCM/ECM interface collection.
	printf '0xef' > "$gadget/bDeviceClass"
	printf '0x02' > "$gadget/bDeviceSubClass"
	printf '0x01' > "$gadget/bDeviceProtocol"
	mkdir -p "$gadget/strings/0x409" "$gadget/configs/c.1/strings/0x409"
	printf 'libra-bringup' > "$gadget/strings/0x409/serialnumber"
	printf 'Linux' > "$gadget/strings/0x409/manufacturer"
	printf 'Mi 4C Alpine %s test' "$protocol" > "$gadget/strings/0x409/product"
	printf 'Serial + %s Ethernet' "$protocol" > "$gadget/configs/c.1/strings/0x409/configuration"
	printf '250' > "$gadget/configs/c.1/MaxPower"
	mkdir -p "$gadget/functions/acm.usb0" "$ethernet"
	printf '02:00:00:00:07:02' > "$ethernet/dev_addr"
	printf '02:00:00:00:07:01' > "$ethernet/host_addr"
	for other in ecm ncm; do
		if [ "$other" != "$network_mode" ] && [ -L "$gadget/configs/c.1/$other.usb0" ]; then
			rm "$gadget/configs/c.1/$other.usb0"
		fi
	done
	for function in acm.usb0 "$network_mode.usb0"; do
		if [ ! -L "$gadget/configs/c.1/$function" ]; then
			ln -s "$gadget/functions/$function" "$gadget/configs/c.1/$function"
		fi
	done

	# Get the selected function's netdev only after the UDC is bound.
	# The function instance name is not evidence that usb0 already exists.
	printf 'Waiting up to %s seconds for a USB device controller...\n' "$wait_seconds"
	controller=''
	n=0
	while :; do
		for udc in /sys/class/udc/*; do
			[ -e "$udc" ] || continue
			controller=${udc##*/}
			break
		done
		[ -z "$controller" ] || break
		if [ "$n" -ge "$wait_seconds" ]; then
			printf 'No UDC: investigate DWC3/PHY/clocks/RPM, not the IP address.\n' >&2
			exit 1
		fi
		sleep 1
		n=$((n + 1))
	done
	printf 'Binding ACM + %s to %s...\n' "$protocol" "$controller"
	printf '%s' "$controller" > "$gadget/UDC"
elif [ ! -L "$gadget/configs/c.1/$network_mode.usb0" ]; then
	printf 'Gadget is bound with a different network mode; reboot to change it.\n' >&2
	exit 1
fi

controller=$(cat "$gadget/UDC")
[ -n "$controller" ] || { printf 'Gadget is still unbound.\n' >&2; exit 1; }
interface=$(cat "$ethernet/ifname")
if [ ! -e "/sys/class/net/$interface" ]; then
	printf 'UDC bound, but %s interface "%s" is absent.\n' "$protocol" "$interface" >&2
	exit 1
fi

# Read the kernel's actual interface name; usb0 is not guaranteed.
if ! ip -4 addr show dev "$interface" | grep -q 'inet 192\.168\.7\.2/24'; then
	ip addr add 192.168.7.2/24 dev "$interface"
fi
ip link set "$interface" up
printf 'USB ACM + %s bound to %s; device interface %s = 192.168.7.2/24\n' \
	"$protocol" "$controller" "$interface"
printf 'Host: use its actual interface name from ip link; set 192.168.7.1/24.\n'
printf 'SSH is not installed; the ACM serial port provides the test shell.\n'
