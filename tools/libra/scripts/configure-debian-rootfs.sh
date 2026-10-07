#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Runs inside the mounted Debian image, under native binfmt/QEMU.
set -eu
cat > /etc/apt/sources.list <<'EOF'
deb https://mirrors.tuna.tsinghua.edu.cn/debian trixie main contrib non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian trixie-updates main contrib non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian-security trixie-security main contrib non-free-firmware
EOF
cat > /etc/apt/apt.conf.d/80libra <<'EOF'
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Retries "3";
Acquire::http::Pipeline-Depth "0";
EOF
apt-get update
apt-get -y dist-upgrade
apt-get install -y \
 systemd-sysv systemd-timesyncd dbus dbus-user-session udev kmod \
 iproute2 iputils-ping dnsmasq-base network-manager network-manager-gnome \
 openssh-server sudo curl wget ca-certificates locales tzdata less nano \
 f2fs-tools util-linux busybox-static libdrm-tests \
 xserver-xorg-core xserver-xorg-input-libinput xinit xauth x11-xserver-utils \
 x11-utils x11-apps xvfb mesa-utils libgl1-mesa-dri libegl-mesa0 \
 lightdm lightdm-gtk-greeter xfce4-session xfce4-panel xfce4-settings \
 xfwm4 xfdesktop4 thunar xfce4-terminal xfce4-appfinder mousepad ristretto \
 xfce4-notifyd xfce4-taskmanager adwaita-icon-theme fonts-dejavu-core \
 fonts-noto-cjk fonts-noto-color-emoji onboard wmctrl xdotool \
 fcitx5 fcitx5-chinese-addons fcitx5-frontend-gtk3 fcitx5-frontend-qt6 \
 fcitx5-config-qt im-config firefox-esr \
 pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth \
 bluez blueman rfkill iw wireless-regdb wpasupplicant pciutils
# Keep signature verification; this kernel trusts the upstream regdb keys.
update-alternatives --set regulatory.db /lib/firmware/regulatory.db-upstream
printf 'en_US.UTF-8 UTF-8\nzh_CN.UTF-8 UTF-8\n' > /etc/locale.gen
locale-gen
update-locale LANG=zh_CN.UTF-8
ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
printf 'Asia/Shanghai\n' > /etc/timezone
printf 'libra\n' > /etc/hostname
cat > /etc/hosts <<'EOF'
127.0.0.1 localhost
127.0.1.1 libra
::1 localhost ip6-localhost ip6-loopback
EOF
if ! id libra >/dev/null 2>&1; then
 useradd -m -s /bin/bash -G sudo,audio,video,input,netdev,render libra
 printf 'libra:libra\n' | chpasswd
 passwd -l root
fi
cat > /etc/fstab <<'EOF'
LABEL=libra-debian / f2fs defaults,noatime 0 0
tmpfs /tmp tmpfs defaults,nosuid,nodev,size=256M 0 0
EOF
mkdir -p /etc/lightdm/lightdm.conf.d /etc/X11/xorg.conf.d /etc/NetworkManager/conf.d
cat > /etc/lightdm/lightdm.conf.d/50-libra.conf <<'EOF'
[Seat:*]
autologin-user=libra
autologin-user-timeout=0
user-session=xfce
greeter-session=lightdm-gtk-greeter
xserver-command=X -nolisten tcp -s 0 -dpms
EOF
cat > /etc/X11/xorg.conf.d/20-libra-modesetting.conf <<'EOF'
Section "Device"
    Identifier "Libra MSM scanout"
    Driver "modesetting"
    Option "kmsdev" "/dev/dri/card0"
    Option "AccelMethod" "none"
    Option "ShadowFB" "true"
    Option "PageFlip" "false"
EndSection
Section "ServerFlags"
    Option "BlankTime" "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime" "0"
EndSection
EOF
cat > /etc/NetworkManager/conf.d/20-libra-usb.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:usb*;mac:02:00:00:00:07:02
EOF
mkdir -p /etc/systemd/logind.conf.d /etc/systemd/journald.conf.d
cat > /etc/systemd/logind.conf.d/50-libra.conf <<'EOF'
[Login]
HandlePowerKey=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore
IdleAction=ignore
EOF
cat > /etc/systemd/journald.conf.d/50-libra.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=32M
EOF
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/50-libra.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication yes
AllowUsers libra
EOF
# This image has no distro kernel/GRUB: its modules match the companion boot.
systemctl set-default graphical.target
systemctl disable apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
systemctl enable ssh NetworkManager systemd-timesyncd lightdm bluetooth
