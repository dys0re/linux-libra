====================================
Xiaomi Mi 4C / MSM8992 bring-up notes
====================================

Status
======

These changes are an ongoing hardware bring-up. On 2026-10-04 the user
confirmed that v7 brings up the USB ACM serial console on the phone and that
v8 USB NCM networking works with the Windows 11 host. The user confirms
multi-core boot works using the six-core simplefb image. Native display and
CPU power-management support remain
unverified. ARM64 Image and both DTBs build successfully; the relevant
device-tree bindings and boot payloads have been checked.

Initial phone testing reaches the initrd with a visible console in both the
six-core simplefb and single-core safe variants. The user reports CX/CX_AO
RPM power-domain timeouts (-110), no ECM netdev, and no host ACM serial port.
This does not establish that all six CPUs are online or that native DRM
works. RPM transport versus individual resource failures remains unresolved;
timeout diagnostics now include message ID, state, resource type/ID and the
first 16 payload bytes. No RPM register or resource ID is changed on the
basis of those incomplete logs.

Follow-up testing reports all RPM power domains timing out, DWC3 at f9200000
waiting for its PHY, and no UDC. Diagnostic v3 also records a read-only SMD
transport snapshot at init and after gadget failure: interrupt count, channel
states, TX/RX FIFO head/tail and packet counters. Pending TX without remote
tail progress points to request delivery/remote processing; pending RX with
no callback delivery points to the receive/interrupt path. These observations
guide further investigation, not automatic proof of a register-address bug.

The user's diagnostic-v2 photos show the first recorded timeout at message
91: sleep-set clock-scaling enable (resource type ``0x306b6c63``, ID 2,
``Enab=1``). Subsequent power-domain and regulator requests time out as well.
The vendor enables scaling after handoff too, but its non-branch handoff
votes convert ``INT_MAX`` Hz to kHz. Mainline's generic handoff previously
sent ``INT_MAX`` directly in wire units. Diagnostic v4 attempted to use the
vendor's ``2147484`` value for MSM8992 only, but its ``DIV_ROUND_UP(INT_MAX,
1000)`` expression overflowed signed int arithmetic. The compiled kernel
contained ``4292819814`` instead, and the user reports that v4 still times
out starting at message 91. Diagnostic v5 casts to unsigned long before
rounding, giving ``2147484`` without changing other SoCs or bypassing
scaling/power-domain errors. The v5 phone photo still shows message 91 timing
out: the SMD channel is open, 91 packets have been sent and 90 received, with
no pending RX packet and equal TX head/tail. The handover correction alone
does not resolve the stall. Getty replaces the missing Alpine BusyBox
cttyhack applet, eliminating the console error loop; required shell applets
are now checked during initrd construction.

Diagnostic v6 enables clock scaling in the active set before the sleep set
on MSM8992 only. The vendor caches sleep-set requests until sleep entry, so
the active-set scaling request is the first one actually sent at startup.
This is an ordering experiment, not a port of the vendor sleep cache: v6
still sends and checks both requests and propagates failures. Successful
active/sleep scaling ACKs are logged separately. With the same handover
sequence, message 91 now targets the active set and message 92 the sleep
set. Other SoCs retain their existing order.

The user reports v6 still timing out at message 91. External comparison found
a directly relevant Libra workaround in ``dys0re/libra-linux-6.1`` commit
``525ba5ca7dffaa36ce6328468c9e4cbc5ff640c2``: skip clock-scaling enable for
MSM8992. The commit describes a multi-core hang, but does not provide a USB
enumeration log. The old Konrad Dybcio ``8994fun`` and SoMainline v5.11-rc4
trees still send sleep-set scaling first; the archived postmarketOS v6.8
package carries board/regulator patches rather than a scaling fix. Another
Libra v7.2-rc tree documents boot support only. These sources establish the
workaround's implementation, not that it will fix this phone.

V7 makes that workaround opt-in via ``clk_smd_rpm.skip_scaling=1`` on MSM8992
only. The kernel parameter defaults to false; the test-image builder adds
it explicitly, and ``RPM_SKIP_SCALING=0`` rebuilds images with the workaround
disabled. Handover, clock votes, RPM power domains and regulator requests
still use the original transport and error checks. The skipped operation
is logged without pretending to have received scaling ACKs. After skipping
scaling, message 91 belongs to a different request; compare its state/type/ID
rather than the number alone. V6 images are retained with ``-usb-v6`` suffixes.
The v7 phone test confirms that the workaround clears the startup blocker
and allows a usable ACM serial console. This establishes that the USB PHY,
controller, UDC and ACM path operate in this tested setup; it does not explain
why the scaling-enable request stalls the RPM firmware. Full RPM logs and
USB Ethernet testing remain useful. DVFS and suspend remain outside this
bring-up.

External reference:
https://github.com/dys0re/libra-linux-6.1/commit/525ba5ca7dffaa36ce6328468c9e4cbc5ff640c2

The reference is the workspace's ``kernel_xiaomi_msm8992`` vendor kernel,
especially ``drivers/usb/phy/phy-msm-hsusb.c``,
``drivers/soc/qcom/cpu_pwr_ctl.c``, ``drivers/soc/qcom/cpu_ops.c``,
``drivers/clk/qcom/clock-cpu-8994.c``, and
``drivers/clk/qcom/mdss/mdss-dsi-20nm-pll-util.c``.

USB implements the USB2 PHY, clocks, reset, CX/MX power-domain votes and VBUS
override for peripheral mode. The CSR/QSCRATCH registers and the 1.2.0
PLLITUNE retention quirk follow the vendor driver. USB3, OTG role switching,
Type-C orientation detection, and charger control are not implemented.

The USB nodes have also been compared to the Mi 4C DTB selected by platform
251, board 12 in the factory boot image. V6 adds the controller's separate
GCC reset at offset 0x03c0 with a 20 ms assertion, explicit XO voting, a
125 MHz master clock, and the DWC3 reference/suspend clocks. The UTMI
property uses the driver's ``snps,hsphy_interface`` spelling. The reference
clock configures GUCTL/GFLADJ for 19.2 MHz; the LPM frame-adjustment selection
and RAM clock-gating workarounds follow the vendor driver. The QSCRATCH RAM
clock bits are applied after the controller reset, before creating the core
device. The MSM8992 wrapper exposes only the two IRQs present in the factory
DTB. V6 still stalled at RPM scaling; USB ACM enumeration and a usable serial
console were subsequently confirmed with the v7 workaround enabled.

V8 defaults to ACM + NCM for the Windows 11 host, whose in-box ``UsbNcm.sys``
supports CDC NCM. ECM remains selectable in the helper as
``libra-usb-gadget 60 ecm`` when the gadget is unbound. NCM uses a different
USB product ID from ECM to avoid the old driver's device cache. Both expose
the phone at 192.168.7.2/24 with the same ACM serial shell. The user confirmed
that USB networking works with this NCM setup on Windows 11. No RNDIS or
unsigned Windows driver is required for this mode.

The RSP61322 video flags also follow the vendor's ``h-sync-pulse=0`` setting:
``MIPI_DSI_MODE_VIDEO_HSE`` is removed because the MSM host maps it directly
to ``PULSE_MODE_HSA_HE``. This corrects a known configuration mismatch, but
does not establish that native scanout works. V8 packages ``libra-drm-test``
for resource listing, interactive test-pattern modesetting and before/after
DRM, clock, regulator, backlight and kernel-log snapshots in RAM.

CPU support is limited to the legacy SCM/ACC **cold-boot** path for four A53
and two A57 cores. CPU preparation selects the 600 MHz GPLL0 auxiliary path;
the clock provider keeps that source enabled. Early SCM extended arguments
must not depend on the tzmem pool, which is created only at driver probe.
There is no DVFS, CPR voltage scaling, CPU hot-unplug, deep idle, or suspend.
Do not stress-test the CPU until the clock/voltage and thermal setup has been
validated. ``maxcpus=1`` bypasses secondary CPU preparation, so that variant
keeps the boot CPU's bootloader clock settings.

Display adds an MSM8992 MDP5 1.10 configuration, DSI host addresses, 20nm
PLL0/auxiliary-PLL1 sequence, and the Sharp RSP61322 burst-video panel. The
native board DT connects MMCC's named byte/pixel parents to the PLL provider;
the simplefb variant leaves those firmware parents disconnected so it does
not depend on the disabled native PHY. The RSP61322 target follows the user's
already-working lk2nd display selection.
The driver preserves the original generic/DCS packet types and initialization
order, including display-on before sleep-out. Other Mi 4C panel variants are
not supported. Dynamic refresh, GPU/Adreno 418, and display IOMMU support have
not been added. Scanout uses the MSM driver's contiguous VRAM fallback with
CMA. The PMI8994 bias driver requires the bootloader to have configured the
LAB/IBB pair for LCD mode; it refuses AMOLED-mode bias rather than changing
the secure selection while the rails may be active.

Build
=====

Run from the workspace root (the parent directory of this kernel tree)::

  sh scripts/build-libra.sh
  sh scripts/build-alpine-initrd.sh
  sh scripts/build-test-boot.sh
  python3 scripts/check-test-boot.py

The configuration and workspace scripts are saved in ``tools/libra/`` in
this kernel repository. For a fresh workspace, place the kernel checkout in
``linux/`` and restore the adjacent script/configuration directories before
building::

  cp -a linux/tools/libra/scripts linux/tools/libra/cfg .

The factory boot image is a separate, read-only build input at the path shown
below. Generated kernel/rootfs/boot images, tool environments, debug photos
and the vendor reference kernel are not stored in this repository.

The kernel configuration is ``cfg/msm8992-libra.config``; no defconfig is
modified. Incremental builds reuse ``build/libra``. Only the two Mi 4C DTBs
are requested. F2FS is enabled.

The builder checks every requested fragment value against the final
configuration, failing if a missing dependency silently drops an option.
Ramoops retains 64 KiB each for panic records and the console, plus 128 KiB
for userspace messages. The unused ftrace reservation is removed so panic
records have space in the existing 256 KiB reserved region. Recovery of these
records across lk2nd reboot still needs hardware verification.

Alpine's aarch64 minirootfs is verified against its published SHA-256 before
extraction. Rootfs work is done only on the dedicated
``build/alpine-3.24.2-aarch64.f2fs.img`` mounted at ``rootfs/``. The builder
refuses an occupied mount point and unmounts after packing. BusyBox, apk,
OpenRC and libdrm's ``modetest`` remain available. The test image uses a small
custom PID 1 rather than launching the full OpenRC boot sequence.

Boot packaging reference
========================

The stock input is read-only::

  libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img

It contains the old Qualcomm Android header with ``dt_size`` at byte 40,
not the newer AOSP ``header_version`` field. The layout is a 4096-byte header
page, an uncompressed ARM64 Image, gzip ramdisk, and a separate QCDT v3 table.
Load-address header fields are copied from stock: kernel ``0x00008000``,
ramdisk ``0x02000000``, tags ``0x00000100``. lk2nd may override these header
addresses and use the mainline Image's text offset.

The factory QCDT keys for platform 251/252, board 12, subtype/revision 0 and
PMIC IDs 65545/65546 are retained; both entries point to the newly built DTB.
Android-only command-line options and the factory verification footer are
not copied. These are unsigned test images for the existing lk2nd, not
factory-signed replacements. lk2nd is not built, changed or flashed.

Testing order
=============

===============================  =========================================
Image                            Purpose
===============================  =========================================
boot-libra-alpine-simplefb.img    Six-core cold boot, retained simplefb
boot-libra-alpine-drm.img         Six-core cold boot + native RSP61322 DRM
===============================  =========================================

From **lk2nd's** fastboot mode, initially boot without writing a partition::

  fastboot boot build/boot-libra-alpine-simplefb.img

The initrd runs entirely in RAM and does not mount the phone's eMMC. USB
configfs exposes ACM serial and NCM Ethernet by default. The device address is
``192.168.7.2/24``; configure the host for ``192.168.7.1/24`` if Ethernet is
needed. Connect to the ACM serial port at 115200 baud.

The selected function's netdev is checked after a UDC is successfully bound.
The USB helper waits up to 60 seconds in the background, checks setup/bind
failures, and uses the actual function ``ifname``
instead of assuming ``usb0``. Its output is saved in ``/run/libra-usb.log``.
Failures also print deferred-probe reasons and recent kernel messages. An
RPM/USB-filtered view includes early messages that may have scrolled out of
the last 80 lines. After
resolving a deferred probe, retry with ``libra-usb-gadget``. On the host, use
the interface name shown by ``ip link``; it need not be called ``usb0``.
There is no SSH daemon in this initrd.

USB networking on Windows 11
============================

The user verified USB networking with v8's six-core simplefb image on
Windows 11. The working function is CDC NCM, alongside the ACM serial shell.
The earlier CDC ECM function appeared with Device Manager code 28 on this
host (driver not installed); that host-driver issue did not establish a USB
transport failure. Windows 11 includes ``UsbNcm.sys``/``UsbNcm.inf`` for NCM.

The NCM test gadget uses VID/PID ``1d6b:0105``; ECM uses ``1d6b:0104``.
The phone's network MAC is ``02:00:00:00:07:02`` and the host's is
``02:00:00:00:07:01``. Changing the product ID may change the Windows COM
port and adapter instance. Use the actual network interface name reported
in ``/run/libra-usb.log`` rather than assuming ``usb0``.

Phone address: ``192.168.7.2/24``. Host address: ``192.168.7.1/24``.
There is no DHCP server. A gateway or DNS server is unnecessary for the
direct host/phone test link. In an administrator PowerShell window, find
the new USB adapter and replace ``17`` below with its actual interface index::

  Get-NetAdapter | Format-Table ifIndex, Name, InterfaceDescription, Status
  New-NetIPAddress -InterfaceIndex 17 -IPAddress 192.168.7.1 -PrefixLength 24
  ping.exe -n 4 -l 1400 192.168.7.2

Successful replies verify host-to-phone and phone-to-host packet transfer.
For phone-side diagnosis over ACM::

  cat /run/libra-usb.log
  ip addr
  ip -s link

If Windows has no working adapter, inspect the NCM function's driver first.
If the adapter exists but ping fails, check the two addresses, interface
state and packet counters. This verification does not establish throughput,
internet sharing, hotplug/suspend robustness, or native DRM display support.
ACM remains the diagnostic shell because this initrd has no SSH service.

Microsoft's in-box class-driver support:
https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/supported-usb-classes

**The test shell has no authentication. Do not use this image as an installed
or network-exposed operating system.**

Collect::

  cat /run/libra-status.txt
  cat /run/boot-dmesg.txt
  cat /run/libra-usb.log
  cat /sys/bus/rpmsg/devices/*/smd_state
  cat /sys/devices/system/cpu/online
  ls /sys/class/udc
  modetest -M msm -c
  cat /sys/kernel/debug/clk/clk_summary

The native DRM image enables verbose DRM logging and automatically runs a
resource scan after five seconds. It does not force a modeset from the initrd.
Over the ACM console, run::

  libra-drm-test scan
  libra-drm-test modeset CONNECTOR_ID CRTC_ID

The second command displays a 1080x1920 at 60 Hz test pattern until Enter is
pressed. Connector and CRTC IDs come from the scan output. Before/after logs
are saved under ``/run/libra-drm/``; the boot scan output is also saved to
``/run/libra-drm-test.log``. Inspect ``modetest-scan.txt``, ``dmesg-after.txt``
and ``state-after.txt`` even if no display connector or modeset is available.

For a modeset test, use the connector and CRTC IDs reported by ``modetest``::

  modetest -M msm -s CONNECTOR_ID@CRTC_ID:1080x1920-60

If the native display goes dark but USB is alive, collect ``dmesg`` and DRM
state over ACM before rebooting. Current builds package only the six-core
simplefb and native DRM variants. Do not flash the test images over lk2nd or
invoke factory flash scripts. No factory images or phone partitions have
been modified by this build workflow.
