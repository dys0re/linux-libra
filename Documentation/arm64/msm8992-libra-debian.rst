Debian Xfce on Xiaomi Mi 4C
==========================

Delivery
--------

``build/rootfs-libra-debian.img`` is an Android sparse image of a 4 GiB F2FS
filesystem, labelled ``libra-debian``. Flash it to the GPT ``userdata``
partition. This replaces the existing contents of userdata.

``build/boot-libra-alpine-drm.img`` retains the established filename but now
contains the Libra ARM64 kernel and a small Debian/glibc initrd. It boots the
userdata filesystem into systemd; Debian is not unpacked into RAM. The initrd
checks the partition name, F2FS type and image label before mounting. On first
boot it expands F2FS offline to the partition size and records completion.

With both files in the host's current directory::

  fastboot flash userdata rootfs-libra-debian.img
  fastboot boot boot-libra-alpine-drm.img

After a successful phone boot, permanent boot installation is::

  fastboot flash boot boot-libra-alpine-drm.img
  fastboot reboot

The initrd contains static ARM64 BusyBox and the Debian tools/libraries needed
for F2FS identification and expansion. Root-mount failure leaves an early USB
serial rescue shell. The final system uses an unprivileged serial login.

Desktop and access
------------------

The root contains Debian 13/trixie arm64, glibc, systemd, APT, Xfce 4.20, X11,
Mesa llvmpipe, Onboard and Fcitx5 Pinyin. APT uses the Tsinghua Debian and
Debian-security mirrors with archive signature verification enabled.

User/password: ``libra`` / ``libra``. The desktop logs in automatically.
Root login is locked; use sudo with the same user password. SSH host keys and
the machine ID are generated on the target, not shared in the image.

USB exports ACM serial and NCM networking. The phone is ``192.168.7.2/24``;
a DHCP server offers the host ``192.168.7.1/24`` without changing its default
route or DNS. The host can also set this address manually. SSH is available::

  ssh libra@192.168.7.2

Internet access over USB requires host-side routing/NAT or connection sharing.
The phone's USB default route points to 192.168.7.1. USB setup precedes native
display handover, and serial/network access does not depend on LightDM.

The X server uses the MSM KMS device with software 2D rendering; OpenGL uses
llvmpipe. Xfwm compositing is disabled. GTK and Qt scaling defaults to 200%,
with large decorations, icons and panel buttons. The panel includes a keyboard
toggle, terminal launcher, window selector and close button. Ordinary application
windows are automatically maximized; dialogs and the keyboard are excluded.
Thunar uses single-click opening. The configuration is initialized once so
subsequent user adjustments persist. Automatic blanking, suspend, hibernate and
lock-screen startup are disabled for this display bring-up stage.

TWRP on this handset identifies Synaptics DSX at I2C address 0x70, with F01
and F12. The updated boot includes RMI4 I2C/F12 support, GPIO60 active-low
reset, GPIO61 level-low interrupt and the factory external touch rails:
GPIO110 for 3.1 V, PM8994 GPIO2 for 1.8 V, and GPIO96 power-down release.
Firmware reflashing support is disabled. The installed display modules remain
byte-identical, so this boot update does not require reflashing userdata.
The user confirmed working touch with the delivered RMI4 boot on 2026-10-06.
This confirms basic operation; detailed coordinate and multitouch measurements
have not been supplied. Diagnose input with::

  sudo evtest
  sudo libinput list-devices
  sudo libinput debug-events

The original desktop image may retain a live second dock after its first-login
panel configuration. ``scripts/libra-panel-fix.sh`` repairs the existing user's
layout without rebooting. New rootfs builds seed a single panel before login.

The keyboard supports Shift+F10 for context menus in applications that implement
that shortcut. Long-press right-click is deferred; the broken distro mousetweaks
daemon is not started or bundled as a working feature.

Validation and memory
---------------------

ARM64 userspace was tested under Xvfb at 1080x1920 for llvmpipe rendering,
scaling, keyboard toggling and automatic maximization. A separate copy was
booted with a Debian generic ARM64 kernel and virtio devices to validate the
userdata discovery, F2FS expansion, switch_root, systemd, desktop autologin
and SSH. The phone image retains the custom Libra kernel; the generic test
kernel and virtio substitutions are not delivery components.

The complete idle desktop ran in a 1 GiB ARM64 virtual machine with roughly
450 MiB used and no swap. On 2026-10-06 the user reported approximately 400M
memory usage after boot on the Mi 4C, below the 1.5 GB requirement. The user did
not specify the measurement tool or exact unit. To use a consistent metric,
after the phone desktop has been idle for 60 seconds, run::

  libra-memory-check

The acceptance limit is strictly below 1,500,000,000 bytes using
``MemTotal - MemAvailable``, including kernel memory. Swap is reported
separately. The user has booted the desktop and confirmed working touchscreen
input on the phone. Repeated-boot reliability remains to be measured.

Rebuild
-------

The real root is only manipulated inside its dedicated F2FS image mounted at
``rootfs/``. Reuse the existing ``build/libra`` kernel build::

  sh scripts/build-libra.sh
  sh scripts/build-debian-rootfs.sh
  sh scripts/build-debian-boot.sh
  python3 scripts/check-debian-images.py

Rootfs builders must not run concurrently. The builder installs matching kernel
modules and all normal system packages, cleans machine identity/keys and package
cache, packs the small initrd, and unmounts the filesystem. Generated package
versions and hashes are written to ``build/debian-package-manifest.tsv`` and
``build/debian-SHA256SUMS``.
