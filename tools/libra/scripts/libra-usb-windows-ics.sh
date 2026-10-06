#!/bin/sh
# Use Windows ICS over the existing ACM + NCM gadget; keep serial available.
set -eu

if [ "$(id -u)" -ne 0 ]; then
 exec sudo /bin/sh "$0" "$@"
fi

apply() {
 interface=$(cat /sys/kernel/config/usb_gadget/libra/functions/ncm.usb0/ifname)
 # Retain 192.168.7.2 so existing host/SSH routes need not be disconnected.
 ip addr replace 192.168.137.2/24 dev "$interface"
 ip link set "$interface" up
 ip route replace default via 192.168.137.1 dev "$interface" metric 900
 printf 'nameserver 192.168.137.1\nnameserver 223.5.5.5\n' > /etc/resolv.conf
 printf 'Windows ICS: phone 192.168.137.2/24, gateway 192.168.137.1 on %s\n' "$interface"
}

case "${1:-}" in
 --apply) apply; exit ;;
 '') ;;
 *) printf 'Usage: %s [--apply]\n' "$0" >&2; exit 2 ;;
esac

target=/usr/local/sbin/libra-usb-windows-ics
mkdir -p /usr/local/sbin /etc/systemd/system /etc/sysctl.d
printf 'net.ipv4.ping_group_range = 0 2147483647\n' > /etc/sysctl.d/60-libra-ping.conf
sysctl -p /etc/sysctl.d/60-libra-ping.conf
if [ "$0" != "$target" ]; then
 install -m 755 "$0" "$target"
fi
cat > /etc/systemd/system/libra-usb-windows-ics.service <<'EOF'
[Unit]
Description=Libra USB network for Windows Internet Connection Sharing
Requires=libra-usb.service
After=libra-usb.service NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/libra-usb-windows-ics --apply
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
# Windows supplies DHCP on this link. The phone must stop serving it.
systemctl disable --now libra-usb-dhcp.service
systemctl daemon-reload
systemctl enable libra-usb-windows-ics.service
systemctl restart libra-usb-windows-ics.service
printf '\nPhone configuration saved. Enable Windows sharing to its USB NCM adapter.\n'
printf 'Test on phone: ping -c 3 192.168.137.1; ping -c 3 223.5.5.5\n'
printf 'SSH from Windows: ssh libra@192.168.137.2\n'
