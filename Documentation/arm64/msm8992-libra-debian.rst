Debian Xfce on Xiaomi Mi 4C
==========================

Delivery
--------

``build/rootfs-libra-debian.img`` is an Android sparse image of a 4 GiB F2FS
filesystem, labelled ``libra-debian``. Flash it to the GPT ``userdata``
partition. This replaces the existing contents of userdata.

The Wi-Fi/Bluetooth test delivery adds QCA6174 PCIe/UART support and matching
modules, OEM firmware and Debian wireless packages. Existing userdata must
install ``build/libra-radio-update.tar.xz`` before booting the new kernel;
reflashing userdata is unnecessary. Extract the archive on the phone and run
``sudo sh libra-radio-update/install.sh``. The old target kernel omitted ``CONFIG_FILE_LOCKING``, whose fcntl stub
returns EACCES even for root. The corrected kernel enables POSIX locks and
requires freshly matched modules because VFS layouts change. On affected
phones, first run ``install.sh --bootstrap`` to copy modules/firmware without
APT or starting radio services, then boot the corrected radio-disabled image.
Run the full installer once POSIX locking works, and then boot the normal
radio image. The installer now tests locking on the running kernel before
starting APT. Offline package tests using the build-host kernel did not
cover this missing target-kernel feature.

The archive includes all new Debian
dependencies for offline installation and a Chinese test guide. Installation
repairs the known image/overlay system-path ownership without changing home
directories. The validated pre-radio images are in
``build/verified-libra-dvfs/``.

Phones already running the build71 radio kernel and packages can instead use
``build/libra-radio-policy.tar.xz``: extract it, then run
``sudo sh libra-radio-policy/install-policy.sh``. This small update installs
the OEM OTP return-code policy, selects upstream-signed regulatory data and
updates startup readiness checks. It does not reflash userdata or reload the
running Wi-Fi driver. The public boot enables the deferred radio service.

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

For Windows Internet Connection Sharing, copy
``scripts/libra-usb-windows-ics.sh`` to the installed phone and run it with
sudo. It disables the phone's DHCP server and persistently adds
``192.168.137.2/24``, default gateway ``192.168.137.1`` and DNS. It keeps the
original 192.168.7.2 address and does not rebind the USB gadget. In Windows,
enable sharing on the Internet-connected adapter and select the phone's USB
NCM adapter as the destination. SSH then uses ``libra@192.168.137.2``.

``etc/sysctl.d/60-libra-ping.conf`` enables unprivileged ICMP echo sockets,
allowing the desktop user to run ordinary ping without setuid or raw-socket
capabilities. The Windows setup script applies this setting immediately to
existing installations. A gateway that does not answer ping is not sufficient
evidence of failed sharing; also test an external IP and an HTTPS request.

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

CPU frequency and temperature support
-------------------------------------

The current delivery enables standard cpufreq policies, schedutil load-based
scaling and the calibrated TSENS thermal zones automatically. A53 can select
the chip's factory speed-bin plan (up to 1.44 GHz on the tested speedbin1
handset); the A57 table includes up to 1.824 GHz. Thermal polling/IRQs and CPU cooling
use the factory 60-degree passive threshold, 10-degree hysteresis and
115-degree critical limit. Automatic DVFS activation requires valid readings
from shared sensor7, A53 sensors9/10 and A57 sensors13/14.

The CPU PLL /4 and /2 paths, auxiliary return, CCI 300/384 MHz transition
and both SAW supply paths have been exercised on this handset. Automatic
policy activation and A53's reported 1.44 GHz have been confirmed. A57's
highest operating point and sustained-load thermal throttling remain
unconfirmed. The previous CCI-tested boot is preserved
in ``build/verified-libra-cci-test``. There is no need to run manual probe or
debugfs test commands on the current automatic image. Use cpufreq and thermal
sysfs to verify its operation. Userspace/powersave governors remain available.

The full source DTB retains power-domain attachments. The factory PLL digital
NOMINAL corner5 is encoded as RPM/GENPD level4; the factory maximum MX corner7
is encoded as level6. The older OEM regulator API offsets corner values by1.
Voltage votes precede frequency increases and follow frequency decreases;
actual CPU rates are sampled for coordination rather than relying on cached
requests. Failed CCI reconfiguration attempts to restore its previous rate.
If restoration fails, CPUs and CCI attempt to return to the verified
600/600/300 MHz auxiliary clocks while retaining the higher supply votes.

Rebuild only the delivered boot with ``sh scripts/build-debian-boot.sh --boot-only``.
This leaves the installed/sparse userdata image unchanged. Effective config
now selects ``CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y``. For the prior CPU-only update, the installed MSM module's code, data,
relocations and symbol ABI were unchanged; rebuilt module differences were
confined to private ``__UNIQUE_ID`` string counters. The current radio delivery
requires its matching module update even though the kernel release is unchanged.

The user booted the automatic image and confirmed the TSENS-ready/cpufreq-ready
messages, schedutil and an A53 policy reporting 1.44 GHz. Only one policy was
listed: the driver had selected the cluster mask before calling
``cpufreq_generic_init()``, whose actual implementation marks all CPUs as
shared. Policy initialization now runs the generic helper first, clears its
mask and then sets CPUs0--3 for A53 or CPUs4--5 for A57. An executable regression
uses the real generic helper and driver initializer for each possible CPU,
reproduces the former overwrite and verifies separate masks/clocks/tables.
The corrected boot should expose policy0 and policy4 independently; its A57
automatic policy and highest operating points await phone confirmation.

The user confirmed the corrected split: policy0 contains CPUs0--3 and policy4
CPUs4--5, with schedutil on both. Policy0 reported a 1.44 GHz limit/current
rate; policy4 reported a 1.6896 GHz limit and 1.344 GHz current rate. This
confirms the two automatic policies, but does not establish why A57's reported
limit is below the table's 1.824 GHz maximum. Temperature/cooling-state checks
and sustained-load/throttling validation were deferred at the user's request.
No thermal-limit adjustment was made from that observation.

Hardware validation is incomplete. The first corrected all-at-boot DVFS image
caused a whole-device reboot before userdata was mounted. No pstore or
persistent kernel journal was recovered, so the trigger is not yet isolated.
CPU/CCI clock probing, TSENS probing and DVFS activation now require separate
manual opt-ins during isolation. The observation images expose manually gated clock and
voltage readers, omits their power-domain attachment, and keeps CPU clock
references on the auxiliary source. It holds all six CPUs at the verified
600 MHz boot path.

The observation kernel uses ``qcom_tsens.msm8992_observe=1`` with the manual
probe flag initially disabled. After a stable boot, enabling
``/sys/module/qcom_tsens/parameters/msm8992_probe`` and probing
``fc4a9000.thermal-sensor`` only maps/reads the controller and calibration.
It does not register IRQs, thermal zones or program thresholds. Valid raw ADC
samples and converted temperatures are available at
``/sys/kernel/debug/tsens/fc4a9000.thermal-sensor/readings``. The common init
helper remains in normal kernel text, so deferred/manual probes cannot call
discarded ``__init`` memory. Observation mode does not validate frequency
transitions or demonstrate working thermal throttling.

The user verified manual TSENS observation on 2026-10-07: all 13 samples had
VALID set and converted to 34--41 degrees Celsius. Primary calibration mode
was 3, with base1=545 and base2=851. This validates basic calibrated readings,
not throttling or temperature accuracy against an external reference.

The next observation DTB, built using
``scripts/prepare-libra-thermal-observe-dtb.py --clocks``, exposes manual
cluster/CCI clock probing while CPU clock references remain on GPLL0 and the
cpufreq node remains disabled. Its clock node omits the power-domain property
to exclude implicit platform power-on during device attachment. With
``clk_cpu_msm8992.clocks_observe=1``, clock objects contain only recalc callbacks,
without critical-enable flags, supply votes or clock-set callbacks. Manual
``clusters_probe`` activation is used to isolate register mapping/readback and
CCI secure reads before introducing voltage or frequency transitions.

The user verified this clock observation on 2026-10-07: A53 and A57 both
read 600 MHz, and CCI reads 300 MHz. The PMIC reports 1,000,000 uV for both
S8/APC0 and S11/APC1. These are reported setpoints, not independent physical
voltage measurements.

The voltage diagnostic DTB uses ``--voltages``. With
``qcom_msm8992_cpufreq.observe=1``, manual driver activation reads the factory
CPR fuse plan and exposes ``/sys/kernel/debug/libra_voltage_observe``. It returns
before power votes, CPR programming or cpufreq registration. SAW state is read
from the factory controllers: APC0 uses the system/CCI SAW at 0xf9065000 and
APC1 uses the cluster1 SAW at 0xf9013000. This diagnostic does not activate the
SAW voltage setter until an explicit manual test request.

Factory ``spm-regulator.c`` routes S8 voltage requests through SAW on CPU0 and
S11 requests through SAW on CPU4; S9/S10 are slave phases. The port-0 request
updates VSET without changing the active PMIC range, and waits for the PMIC
acknowledgment. The regulator backend now supports separate SAW controllers
and CPU affinity for these requests. The current test DT wires S8 to CPU0's
system/CCI SAW and S11 to CPU4's L2 SAW; S9/S10 remain slave phases.
The previous experimental implementation used ordinary SPMI voltage setting.
That differs from the factory route, but has not been established as the cause
of the reset.

The user confirmed another whole-device reset during the combined manual
clock/voltage observation command on 2026-10-07. No final stage marker was
captured, so the triggering operation is unknown. The public boot was restored
to the verified clock observation image (SHA256 starting ``67ee837b85f5``).
The new voltage image's contiguous 0x500-byte fuse read differed from the
factory's selected-row access. Source now reads individual 8-byte cells:
selector row62 first, revision row137 and speed-bin row22, then primary
rows138--140 or redundant rows56/57/136. Unrelated rows and the unused bank
are skipped. Executable provider tests reject any unrelated read and verify
that read errors stop access. This correction has not yet been tested on the
phone and is not identified as the proven reset cause.

The user then reprobed the restored clock observation image successfully.
Attempting to probe ``f9019000.cpufreq`` returned an I/O error because that
image disables the cpufreq DT node. This is an expected failure of the combined
command, not a successful voltage probe. The public boot is now the corrected
selected-row observation image (SHA256 starting ``35679a91a088``). Validate
clock registration first, then run a separate logged cpufreq observation probe
to capture calibration and calculated voltage plans. Defer reading the SAW
debugfs report until that probe has been confirmed stable.

The user confirmed both separate probes on this image. Corrected rows62,
137,22,138,139,140 and the raw speed-bin row were read successfully. APC0
is speedbin1/revision4/primary, with calculated top corner 1.44 GHz at
1,150,000 uV. APC1 is speedbin0/revision4/primary, with calculated top corner
1.824 GHz at 1,110,000 uV. The observation probe returned successfully after
mapping both SAW controllers. These are calibrated target voltage plans;
neither actual frequency transitions nor SAW register readback have yet been
validated. The verified boot and supplied voltage plans are preserved in
``build/verified-libra-cpr-observe``.

The user subsequently read both SAW banks without a reset. CPU rates remain
600/600 MHz and CCI 300 MHz; both PMIC setpoints are 1,000,000 uV. APC0's
PMIC_STS, VCTL, AVS_CTL and PMIC_DATA_3 were zero. APC1 reported PMIC_STS=0xb8,
VCTL=0x00030080, AVS_CTL=0 and PMIC_DATA_3=0. The 0xb8 status matches the PMIC
range0 encoding for 1,000,000 uV. A zero command/status bank alone does not
establish whether a controller is configured for voltage changes. Both SAW
addresses and CPU lists were compared against the selected factory DTB.
The latest report adds read-only CFG, SPM_CTL, SPM_DLY, PMIC_DATA_0--2 and
VERSION registers to check the factory configuration before any voltage write.

Both extended reports showed SAW v3.0, CFG=0, SPM_CTL=0, SPM_DLY=0 and
PMIC_DATA_0--3=0. Factory voltage-command configuration is now applied lazily
on the first manual voltage request: CFG=1, delay=0x3c100c00 (A53) or
0x3c100c30 (A57), PMIC_DATA_0=0x00030000 and PMIC_DATA_1=0x02030080.
The setter verifies v3.0 and PMIC-arbiter presence before setup, runs on
CPU0/CPU4, and preserves sleep sequencing. Setup failures do not issue a
voltage command. This does not add idle or suspend support.

The test boot keeps clock observation and cpufreq observation enabled, and
adds ``qcom_msm8992_cpufreq.saw_test=1``. A root write of cluster index 0 or 1
to ``/sys/kernel/debug/libra_saw_voltage_test`` explicitly requests a
1,000,000 -> 1,005,000 -> 1,000,000 uV pulse on that rail. Both CPU clusters
must still read 600 MHz and CCI 300 MHz, and the selected rail must report
1,000,000 uV before starting. PMIC readback is checked after each request.
On error the test stops; if restoring the baseline fails, the raised voltage
is retained. No CPU/CCI rate change or cpufreq policy registration occurs.
The driver still does not write voltage/configuration during boot or the
manual observation probe. The pulse and lazy SAW setup have host executable
tests but are awaiting phone validation. Test A53 first, then A57 separately.

The user verified both voltage pulses on the phone: each reported 1,005,000 uV
after the upward request and 1,000,000 uV after restoring the baseline. Both
SAW banks now read CFG=1, their factory delay values, PMIC_STS/VCTL/DATA_3=0xb8
and the factory DATA_0/1 values. No CPU frequency transition was involved.
This verifies the two small SAW-controlled transitions, not the complete DVFS
range or regulation accuracy measured externally.

The current clock-test image adds ``clk_cpu_msm8992.clocks_test=1`` and
``qcom_msm8992_cpufreq.clock_test=1``. Manual CPU clock callbacks are enabled
without critical clock flags or automatic power/rate changes at registration;
CCI remains read-only. Root writes in Hz to ``libra_a53_clock_test`` or
``libra_a57_clock_test`` select a persistent CPU rate. A53 initially supports
384/460.8/600/672 MHz, and A57 384/480/600 MHz. Both supplies must report
1,000,000 uV and CCI 300 MHz. The selected rate must occur in the factory
clock plan, fit its calibrated voltage including the transient 600 MHz path,
and require no more CCI bandwidth than the existing 300 MHz rate. Failed
PLL locking leaves the CPU on the auxiliary 600 MHz source; actual clock
readback is checked and failures are returned. This stage validates PLL/mux
switching before CCI rate changes, full cpufreq policies and thermal throttling.
The boot still starts at 600 MHz and does not automatically select a faster rate.

The user verified A53 600 -> 384 -> 600 -> 672 MHz and A57 600 -> 384 ->
480 -> 600 MHz. All callbacks returned zero and hardware readback matched
each requested rate. CPU PLL main /4 and /2 paths, and auxiliary return,
have thus been exercised on both clusters; early outputs and higher rates
remain untested. The verified boot is preserved in
``build/verified-libra-cpu-clock-test``.

The current test boot exposes ``libra_cci_clock_test`` with both provider and
consumer ``cci_test=1`` parameters. Root requests can select 300 or 384 MHz
while both CPUs remain at 600 MHz and APC0 reports 1,000,000 uV. The target
must fit the calibrated APC0/CCI voltage plan. Readback is checked; failed
PLL/mux requests attempt to restore the boot auxiliary 300 MHz CCI rate.
The original error is still returned and recovery results are logged. CPU
bootstrap requests can operate with CCI at either 300 or 384 MHz, still
within their existing frequency limits and the factory CCI mapping. The
CCI transition is awaiting phone validation. Automatic cpufreq policies and
thermal-zone activation remain disabled in this test boot.

The experimental full DVFS implementation adds built-in MSM8992 TSENS calibration,
cluster/CCI clocks and a dedicated cpufreq driver. The four A53 CPUs share
policy0 (384 MHz up to 1.248 GHz for speedbin0, or 1.44 GHz for speedbin1).
The two A57 CPUs share policy4 (384 MHz up to 1.824 GHz). During validation,
the default governor was userspace; schedutil was built but not selected
automatically. The A57 policy also includes its 600 MHz auxiliary boot point,
so policy registration cannot force an immediate move to 633.6 MHz merely
because the initial rate was absent from the table. CPU cooling can limit the
policies when hot. The factory frequency plans are selected from the chip's
speed-bin fuse.

APC voltages come from the factory CPR open-loop calculation: primary or
redundant per-corner fuses, revision/RO matching, signed voltage adjustments,
capped interpolation, 5 mV rounding and per-corner voltage limits. The copied
constant tables are tested against the selected factory DTB. Autonomous CPR
loops are disabled; closed-loop adaptive voltage reduction is not implemented.
CPU hot-unplug, deep idle and system suspend remain unsupported.

PLL0 is reprogrammed only while its cluster runs on the existing 600 MHz
GPLL0 auxiliary path. Its main /4, main /2 and early outputs cover the factory
1209.6--1996.8 MHz VCO range. The MSM8992/v2 settings and lock delays are
preserved. Lock failure leaves the cluster on GPLL0 and returns an error.

CCI follows the maximum requirement of both clusters using the factory
CPU-to-CCI maps. Its secure mux is accessed through SCM. A53 and CCI share
APC0, so lowering A53 frequency cannot lower its voltage below CCI's demand
while A57 is fast. Supplies are raised before clocks; clocks are lowered
before supplies. Both supplies also cover the transient 600 MHz CPU auxiliary
source. CCI reconfiguration uses its 150 MHz auxiliary path. An unsuccessful
transition retains excess voltage rather than undervolting an active clock.
RPM VDDMX receives the factory maximum corner vote; existing maximum BIMC/NoC
handoff votes are retained. Dynamic interconnect bandwidth scaling is not
implemented by this change.

The cpufreq driver registers only after the calibrated TSENS zone is available
and can return a temperature. Calibration failures leave the original 600 MHz
boot path available, without enabling the high-frequency policies.

The driver uses factory physical sensor IDs 0--5, 7, 9--14 and decodes the
chip's primary or backup two-point calibration. Primary offsets are packed
by software index; backup offsets use hardware sensor IDs. Backup base bit 0
and offset-5 bit 3 are assembled at their named bit positions; the old OEM C
implementation omitted those destination shifts. Unsupported calibration
modes fail probe rather than using synthetic 532-code temperatures.
Sensor control/calibration fuses are not rewritten. The enabled TSENS control
state is inherited from firmware, as in the factory type-2 implementation.
The type-2 control register is SROT + 0x4, matching the Qualcomm 1xxx
layout. SROT + 0x0 is not the enable register. The A53 mux bank is shared
with the existing APCS IPC mailbox: mailbox writes use +0x8, clock mux
writes use +0x54. Its mapping is shared rather than claiming the mailbox's
region a second time. The A57 bank retains an exclusive resource mapping.

All 13 zones poll every 250 ms. CPU sensor7 limits both clusters; sensors9/10
also limit A53, and sensors13/14 limit A57. Passive throttling starts at
60 degrees Celsius with 10 degrees hysteresis. The emergency limit remains
115 degrees, matching the selected factory DTB. These are chip temperatures,
not surface temperatures. Primary/backup decoding and clock/voltage failure paths
have host-side executable tests and compiled DT comparisons; actual sensor
readings, transitions and thermal throttling still require phone validation.

The diagnostic helper ``tools/libra/debian/usr/sbin/libra-cpu-status`` reports
policies, current rates, temperatures and cooling states without changing
anything. New rootfs builds include it. Existing userdata can instead use::

  cat /sys/devices/system/cpu/cpufreq/policy*/scaling_available_frequencies
  cat /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq
  for z in /sys/class/thermal/thermal_zone*; do
      cat "$z/type" "$z/temp"
  done

Cpufreq sysfs uses kHz; thermal sysfs uses millidegrees Celsius. Cluster clock
debugfs ``msm8992_a53/clk_rate`` and ``msm8992_a57/clk_rate`` read back the
actual mux/PLL settings in Hz; the auxiliary clock alone is no longer the
current CPU rate. The boot retains kernel release 6.12.112+ and the installed
CPU-only display module load image/relocations were unchanged. That older
CPU-only boot did not require a module update; the radio boot does.
For the diagnostic variant, validate with
``python3 scripts/check-debian-images.py --boot-only --dtb build/libra-voltage-observe.dtb``.

Wi-Fi and Bluetooth first-test support
-------------------------------------

The selected factory x11 DTB uses QCA6174 WLAN on PCIe0 at fc520000 and Rome
Bluetooth on BLSP2 UART2 at f995e000 (GPIO45--48). GPIO113 is WLAN_EN;
GPIO112/54/53 are all-high PCIe boot straps. PM8994 GPIO19 controls BT_EN.
A single fixed regulator owns the shared PA switch on PM8994 GPIO9, with the
factory 4 ms startup delay. WLAN and Bluetooth each hold independent votes
on this switch, S4 IO and L30 crystal supplies. WLAN follows PA/IO/crystal,
then each bootstrap high for 10 ms, then WLAN_EN and 10 ms. Straps stay low
before activation and return low before IO power removal. Bluetooth follows IO/crystal/PA, then reset low/high
with 50 ms each and 100 ms before supply removal.

The new PCIe host follows the OEM aperture, MSI/INTx IRQs, auxiliary clock,
GDSC/LDO and SCM device11 sequence. Target snapshots showed both outer
PHY reset (GCC+1b18) and PIPE reset (GCC+1b14) asserted. The outer reset is now
released before strict CCF AUX clock enable checks; the PIPE reset is released
after PHY programming and before PIPE clock activation, matching the OEM
PIPE branch reset operation. A separate PHY driver applies all 48 factory
vbg-opt 20nm register writes in order. GCC now models PIPE as the PHY's 125 MHz output,
rather than an XO-derived clock. The initial Gen1 restriction has been
removed; the host retains the hardware's default link capability as OEM does.
No interconnect driver or deep PCIe suspend/hotplug support is added.

Target build66 snapshots confirmed GDSC on, LDO on, outer reset released,
AUX M/N configured, and the AUX root running, but the AUX branch remained gated
before PHY/link initialization. The OEM branch callback warns but continues
through this phase. MSM8992 AUX now uses an initial request/delay policy;
AUX and PIPE running/enable bits are polled with a bounded timeout after
LTSSM activation. The delay is scoped to MSM8992; halted clocks after startup
still fail probe. Build67 reached PHY readiness and confirmed both AUX and
PIPE running, but only the Root Port enumerated. Comparison with factory
``pci-msm.c`` found the LTSSM enable belongs to PARF+0x1b0 bit8; the first
implementation incorrectly used the older controller's ELBI+0x04 bit0.
The MSM8992 operations now select the existing PARF callback. A single
post-training snapshot records PARF, ELBI and DBI link state. Endpoint
enumeration still requires phone validation.

Build68 confirmed PARF LTSSM bit8 set, but the sampled DBI LTSSM state was
Detect.Active (1), ELBI lacked XMLH_LINK_UP and no endpoint enumerated.
Touch input remained functional after this test. A further clock comparison
found the factory ``pcie_pipe_source_val`` is 2, while the initial mainline
mapping incorrectly used 0. PIPE sources now model reset-state XO as 0 and
the PHY output as 2, so the reset source is not reported as a 125 MHz PHY
clock. Tests derive expected selector values from the unmodified factory
clock driver and reproduce the wrong-selector case. GCC PIPE CMD/CFG are
included in the staged snapshots; phone verification remains necessary.

Build69 confirmed PIPE CFG=0x201 and both clock roots running. The sampled
LTSSM advanced to Polling.Active (3), but no endpoint enumerated; display and
touch remained functional. The next delivery sets the OEM 4096-byte MRRS
before LTSSM and delays the OEM N_FTS bit15 update until the link is up.
The PHY's debugfs ``status`` file reads selected factory-dump registers under
the PHY mutex and refuses MMIO while powered off. Its PLL/reset, RX signal,
PCS and revision readings are for diagnosis, not proof of a working link.

Build70 confirmed MRRS=4096 and hardware-default Gen2 capability, but remained
in Polling.Active without an endpoint. PHY PCS_STATUS=0x84 passed the OEM
ready check (bit6 clear); RX_RX_SIGDET read zero. The CNSS initial-resource
path powers all three WLAN rails before driving the straps high. The first
implementation had instead raised them during regulator probe, before enabling its supply votes.
Bootstrap high transitions now occur inside the powered enable callback, and
disable clears them before removing IO. This matches the factory initial
sequence and avoids driving high strap signals into an unpowered IO supply.
Build71 verified Gen1 x1 link-up and the QCA6174 hw3.2 endpoint 168c:003e.
The original board and firmware were accepted by ath10k. Following the OEM
OTP return policy enabled association, DHCP and SSH over 5 GHz Wi-Fi.


The firmware extraction script reads the supplied ``NON-HLOS.bin`` and
``BTFM.bin`` as FAT16 without modifying or mounting either image. It wraps
unchanged ``qwlan30.bin`` and ``otp30.bin`` in an ath10k API5 container with
WMI TLV (4), HTT TLV (3), and the firmware-scoped ignore-OTP-result bit7.
Factory qcacld executes OTP with param0 after board loading without rejecting
its return code; this image returns2. The flag follows that policy while
retaining OTP download/execution and all transfer/execute error checks. It
does not change the OTP payload or globally enable the test-mode module
parameter. The temporary ``skip_otp=1`` diagnostic was verified on the phone;
the persisted firmware flag and automatic cold-boot startup await verification.
``bdwlan30.bin`` is the board data, not ``bd30_a10.bin`` or generic data.
The Bluetooth patch/NVM are byte-identical to the OEM files, with loader
filenames for Rome3.2. SHA256 provenance is installed at
``/usr/lib/firmware/libra-oem-radio-manifest.json``. No persist calibration or device identity files are copied from the flashing
package, and no downloaded radio firmware is used.

NetworkManager uses a persistent local MAC and disables Wi-Fi power saving
for initial validation. BlueZ/Blueman, wpasupplicant, iw, rfkill, pciutils,
regulatory data, Bluetooth input and PipeWire Bluetooth components are
installed. The image and installer select ``regulatory.db-upstream`` via
update-alternatives, because the kernel trusts upstream sforshee/wens keys;
Debian's higher-priority default uses a different signature. Signature
verification remains enabled. The signed upstream selection was verified on
the phone. A root helper assigns a persistent local Bluetooth address only
when the kernel reports an unconfigured controller; existing valid addresses
are preserved. It uses the Linux management channel, compatible with Debian's
Python3.13 HCI socket ABI. It never edits the OEM NVM file.

The public boot enables ``libra.radio=1`` after build71 PCIe/firmware/Wi-Fi
traffic validation. Recovery uses ``libra.radio=0`` with the matching kernel,
DTB and initrd and keeps both PCIe activation and UART autoload off. Fresh
rootfs USB networking defaults to 192.168.7.2; the old 192.168.137.2 address
requires reconfiguration.

PCIe probing is initially held; ``libra-radio.service`` activates it and UART
Bluetooth after root, USB and native display startup. UART autoload is
blacklisted so ``libra.radio=0`` also keeps Bluetooth off. A same-kernel
radio-disabled recovery boot is in ``build/archive/libra-radio-disabled/``.
Startup now requires the endpoint's registered ieee80211 PHY, rather than
accepting an empty Root Port as radio success. Bluetooth firmware setup,
power-on and discovery worked alongside Wi-Fi. Initial UART setup still
logged frame-reassembly -84, and discovery logged one unexpected command
completion length for 0x041a; these remain tracked. Pairing/audio are deferred
at the user's request. Long-term coexistence, throughput and cold-boot startup
remain unverified. The phone was powered off by the user when warm, before
the persisted policy update could be installed or tested remotely.

On the phone, collect ``sudo libra-radio-status`` and the radio service
journal. Connect with ``nmcli --ask device wifi connect 'SSID'`` or the taskbar
network applet; use Blueman or bluetoothctl for discovery and pairing. Do not
repeat activation after a whole-device reset; retain one boot's logs first.


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
