========================================
Xiaomi Mi 4C bring-up history (v6-v34)
========================================

This is the historical investigation record preserved from commit
``ca4073de9``. Statements describe the corresponding test version; old
experimental commands and interfaces are not current instructions.
For the effective configuration and supported test actions, see
:doc:`msm8992-libra`.

Status
======

These changes are an ongoing hardware bring-up. On 2026-10-04 the user
confirmed that v7 brings up the USB ACM serial console on the phone and that
v8 USB NCM networking works with the Windows 11 host. The user confirms
multi-core boot works using the six-core simplefb image. Subsequent testing
reports abnormal display and problems with both ACM and USB networking in
the v8 native DRM image. V9 still does not expose USB even with MSM fbdev
disabled. The successful USB result applies to simplefb;
native DRM is not validated. CPU power-management support also remains
unverified. ARM64 Image, display modules and three DTBs build successfully; the relevant
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

V9 separates native driver probing from the first scanout test. The v8
initrd did not request a modeset, but MSM's default fbdev client could still
perform one during driver registration under the console lock. V9 sets
``msm.fbdev=0`` only in the native image, disables automatic resource scans,
and uses ``drm.debug=0x7`` with a 2 MiB kernel log buffer instead of enabling
every DRM debug category. This is a diagnostic isolation step, not evidence
that fbcon is the cause of the reported failure. Native initialization still
probes the display, PHY, panel and their clock/power dependencies.

The user reports that V9 still has no USB. USB is the only verified input
channel, so logs saved solely in RAM are insufficient if probing kills it.
This result does not identify the failed probe or exclude an early modeset;
it establishes that disabling the fbdev client alone is insufficient.

V10 builds MSM DRM (including its DSI PHY), the panel, LAB/IBB and WLED as
modules, packages those exact modules with matching release/dependency
metadata, and never loads them in init. ``boot-libra-alpine-drm.img`` now
uses ``msm8992-xiaomi-libra-drm-late.dtb``: the firmware framebuffer remains
enabled while the native nodes await manual driver loading. MMCC has no DT
dependency on the unloaded DSI PLL; MSM8992 byte0/pixel0 clocks can instead
resolve their parents by clock name when the PLL module registers them.
Other SoCs retain their firmware parent lookup. The late image also uses
``clk_ignore_unused pd_ignore_unused`` to retain firmware display resources
until handover, and disables the native MSM fbdev client.

ACM getty starts before status output in both current images. V10 restores
the local simplefb console and loads one display stage at a time through
``libra-drm-load``. The helper streams new kernel messages to the existing
USB terminal before modprobe, so the host can keep the last output even if
the link fails. Before loading MSM it unbinds simpledrm, releasing its clock
references before the new PLL provider reconnects orphan parents. No scan
or modeset is automatic. The USB descriptors, IP addresses, CPU settings
and RPM workaround are unchanged. The user's V10 transcript confirms a
working ACM shell through bias, backlight and panel module loading. Those
module insertions returned zero; the transcript does not establish their
device binding or NCM operation in this run.

The V10 MSM stage faults at ``clk_divider_recalc_rate+0x18`` with a synchronous
external abort, and modprobe returns 139. The call stack reaches
``dsi_pll_20nm_8992_init+0x150`` through the first divider registration. The
matching object disassembly identifies an unconditional read of PLL0's
``POST_DIVIDER_CONTROL`` at offset 0x140 (physical 0xfd994440). Its address
and mapping extent match the vendor register layout. The PHY probe enables
GDSC/AHB before registering clocks, but does not enable its analog supplies;
the vendor wraps divider/mux register reads with PLL resource enable.

V11 removes PLL MMIO from clock registration and rate/parent queries. The
MSM8992 divider and byte-mux callbacks cache the desired configuration in
RAM, using the common clock framework's divider/mux calculation helpers.
Clock changes are gated while prepared. PLL prepare enables analog supply
references, applies the cached divider/mux settings, then performs the
existing calibration/lock sequence. Lock failure and unprepare balance
these supply references. The desired state survives PHY reset and GDSC off,
so reading hardware solely to save/restore divider state is no longer needed.
The generic MSM8994 PHY configuration is unchanged.

Mocks of the actual C functions check zero MMIO during clock registration
and powered-off queries/configuration, field preservation, supply errors,
both lock timeout paths, balanced cleanup and repeated cold prepare. These
tests cannot verify physical PLL lock or scanout. The V11 phone transcript
reports WLED probe error -22 for the invalid boost-limit value, followed by
a hang in the combined framebuffer-release/MSM stage. Its last visible
marker says framebuffer release, but the log replay obscures the later
records, so that excerpt cannot identify the exact hanging call. The V11
wall-clock log filter still replays boot history on the phone despite passing
the host/ARM64 fixture test. ``drm.debug=0x6`` retains driver/KMS messages
without core object-reference tracing. Reboot before testing after an Oops;
do not retry native DRM operations in that faulted kernel.

V12 corrects the board's WLED configuration against the factory DTB selected
by platform 251, board 12 and the recorded PMIC IDs: two LED strings, 20 mA
per string, 600 kHz and 29.5 V OVP. The vendor's boost-limit property 980 is
converted to register index 3 by its ``980 / 280`` calculation; the mainline
PMI8994/WLED4 table calls that entry 620 mA. This preserves the vendor's
register encoding instead of treating the raw property as a mainline enum.
The previous 16 mA and 29.6 V values also fail PMI8994's driver tables. The
OVP binding now distinguishes PMI8994's values from generic WLED4 values.

V12's small ARM64 ``libra-kmsg`` utility opens ``/dev/kmsg`` and seeks to its
current end **before** forking the requested command. It streams the new
records and saves their raw sequence numbers/monotonic timestamps, draining
available records after the child exits. It needs no calendar time or host
libc, and does not clear the kernel log. Tests on the host and the ARM64
binary confirm no boot replay and preserved exit/signal statuses. The loader
checks that WLED created a bound backlight device, reports a failed binding
as stage failure, and refuses MSM loading if that check fails. Module-only
presence is still insufficient to establish bias/panel binding.

Framebuffer release is a separate ``libra-drm-load release`` command. MSM
loading refuses to unbind a framebuffer implicitly; it requires the release
stage to have completed. Check USB between these actions. New MSM8992 PHY/
PLL registration markers help locate any remaining probe stall.

The V12 phone test confirms WLED binding and successful framebuffer release
with ACM still available. Its MSM log completes all PLL clock registration
markers, establishing that the earlier PLL registration fault is bypassed.
It then faults in ``msm_dsi_host_init+0x2d8`` in
``deferred_probe_work_func``. Disassembly identifies the failing read as
the legacy VERSION offset 0x1f0, physical 0xfd9941f0. Modprobe returns zero
because the failed work runs asynchronously; native scanout is not validated.

V13 adds an MSM8992-only bootstrap resource description for version probing.
It gets and enables the four vendor bus clocks (mdp_core, iface, bus,
core_mmss), checks runtime resume, and holds the four host supply references
before reading the controller. The compatible identifies DSI6G; its actual
hardware revision is read at offset zero, matching the vendor path, rather
than probing the legacy/scratch offset. The read revision still selects and
validates the configuration; it is not replaced with a fabricated version.
All acquired enable references are balanced on success and errors, including
deferred resource acquisition. The host reuses the supply handles acquired
for this probe. Other platforms retain their existing discovery path. Mutex
initialization now precedes early initialization errors so teardown is valid.

V13 removes the redundant ``qcom,num-strings`` property; the explicit two
enabled strings remain. The loader rejects further operations after machine
check/Oops, captures deferred workers for one second after MSM insertion,
and treats absent native DRM binding or a worker fault as failure even if
modprobe returned zero. Nine mocked C resource/read scenarios and five
loader scenarios cover these conditions. These checks do not establish
physical register accessibility or display operation. V13's phone log shows
that reading offset zero still externally aborts after bus clocks/supplies
are enabled. This disproves a register-offset-only explanation. The phone
also lacks ``/proc/sys/kernel/tainted`` because ``CONFIG_PROC_SYSCTL`` was
disabled. The user reports an expanding screen halo during the failed test,
and confirms the display recovered after shutdown.

Further vendor audit identifies a missing MDSS power-on step. Its
``__mdss_restore_sec_cfg`` enables AHB, AXI and MDP core clocks and calls
``scm_restore_sec_cfg(1, 0)`` on ``REGULATOR_EVENT_ENABLE``. The mainline
port did not restore this security configuration when MDSS powered up.
This omission is a plausible explanation for the inaccessible DSI/PLL
registers; it has not yet been established by hardware testing.

V14 enables the MDP core clock in MSM8992's parent MDSS device and invokes
``qcom_scm_restore_sec_cfg(QCOM_SCM_MDSS_DEV_ID, 0)`` at runtime resume,
before child register access. SCM unavailability or restore failure prevents
further probe and releases clock/interconnect votes; positive firmware
error statuses are converted to negative runtime-PM errors. Other SoCs keep
their existing clock discovery and do not use this restore path.

The late DRM image defaults WLED brightness to zero. The loader keeps it
off before framebuffer release/native probing and on errors. Panel probe
requests GPIOs as-is; direction/output changes occur only in prepare after
the bias supply references are enabled. These changes avoid lighting the
panel or resetting it merely to register its driver. V14 enables
``CONFIG_PROC_SYSCTL`` and falls back to kernel error records if the taint
file is missing or malformed; missing diagnostics are no longer treated as
an empty numeric taint value. Six mocked secure-restore scenarios, five
panel GPIO/supply scenarios and five fault-fallback scenarios pass. V14
phone testing confirms successful secure restore, actual DSI revision
0x10030000, MDP5 v1.10 registration and native DRM binding without the prior
external abort. A resource scan succeeds with connected DSI-1 connector 33,
CRTC 88 and the preferred 1080x1920 at 60 Hz mode. This establishes resource
enumeration, not scanout or physical PLL lock.

V14's scan log later reports core clock enable -110 while runtime-resuming
the PHY clock provider. The diagnostic helper's ``clk_summary`` reads are
active: ``clk_summary_show`` calls ``clk_pm_runtime_get_all`` before walking
the clock tree. Thus a snapshot can wake MDSS after the resource query has
finished. The full log identifies ``core`` rather than an RPM ACK timeout.
MDP initialization requests its configured 400 MHz maximum, whose frequency
table uses MMPLL0; its successful initial 200 MHz path uses GPLL0. The exact
cause of the later enable timeout has not been established. ``CONFIG_BUG``
was disabled, suppressing the clock driver's WARN diagnostics.

V15 uses the opt-in ``msm.mdp5_core_clk_rate=200000000`` parameter in the late
DRM image and its load helper. The hardware maximum remains 400 MHz; other
builds default to that existing maximum when the parameter is zero. This
bring-up operating point avoids requesting the unvalidated MMPLL0/high-rate
path. Core rate-setting failures and MDP clock-enable failures are now
propagated; partial enables unwind and register reads in revision/KMS
initialization check runtime resume. ``CONFIG_BUG`` enables WARN reporting.
Neither MMPLL0 operation nor display performance is established by this
experiment.

V15 snapshots replace ``clk_summary`` with the plain software
``clk_prepare_count`` and ``clk_enable_count`` files, saved to
``clk-counts-before.txt`` and ``clk-counts-after.txt``. They do not read
``clk_rate`` or ``clk_parent`` callbacks. Seven mocked enable/rollback cases
and a snapshot test that rejects active clock reads pass. The V15 phone log
confirms an actual 200000000 Hz core clock, successful MSM binding and a
resource scan returning zero with connector 33, CRTC 88 and 1080x1920-60.
The supplied post-scan excerpt no longer contains the prior clock timeout.
MMPLL0 operation remains unverified; the backlight remains off. The user's
first dark modeset reaches D-PHY configuration and requests 140640000 Hz
pixel and 105480000 Hz byte clocks, then times out waiting for the DSI PLL.
Host power-on fails, followed by vblank timeout and flip/commit cleanup
timeouts. Those later errors do not establish independent MDP failures.

V16 fixes two confirmed discrepancies in the PLL cold configuration:
PHSEL_CONTROL at offset 0x18 was missing (vendor value 0x08), while
IPTAT_TRIM_VCCA_TX_SEL at offset 0x1c incorrectly contained 0x08 instead
of 0x0e. An automated comparison resolves the vendor macros from both its
PLL header and source and confirms all 23 common/loop-bandwidth writes now
match offsets, values and order. V16 logs the requested VCO/divider state
and distinguishes calibration bit-5 timeout from ready bit-6 timeout, with
register readback captured before powerdown. Lock success is logged too.
Both stages still require hardware status; no error is bypassed.

V16's DRM helper examines the new post-test kernel messages and reports
PLL/power/vblank/commit errors as a failed test even when modetest returns
zero. Five status-classification scenarios and the updated PLL resource/
timeout cleanup mocks pass. Physical lock and scanout are still pending.

The V16 phone transcript reads back the corrected trims but still times
out in calibration at status 0x96. Host power-on then fails and RMFB cleanup
reports vblank, flip/commit timeouts and an atomic-flush warning. These
occur after the first PLL failure; they do not prove a separate MDP fault.

V17 corrects a polling API translation error. The downstream definition in
``include/linux/iopoll.h`` takes ``max_reads, time_between_us`` for
``readl_poll_timeout_noirq()``. Its PLL invocation ``15, 1000`` means 15
reads separated by 1 ms, independently for calibration bit 5 and ready
bit 6. Our prior mainline invocation instead used 15 us between samples
with only a 1 ms total timeout. V17 preserves the vendor's bounded loop
and busy-delay semantics for both stages, including the final delay on
failure. No trim, voltage, frequency or success condition changes. Sixteen
timing cases match the exact downstream macro's reads, delays, status and
return value, including its last-sample boundaries. Delayed calibration
and ready stages and timeout/resource-cleanup mocks pass. The physical
PLL still needs a new dark modeset test on the phone.

The V17 phone log confirms PLL lock at status 0xf5, roughly 11 ms after
the start marker, followed by completed DSI command transfers and vblank
events. RMFB cleanup completes without the previous flip/commit timeouts.
It reports one INTF1 underrun (bit 26, 0x04000000) at initial enable; the
transcript alone does not establish whether this is transient or sustained,
and a visible test pattern has not been confirmed.

V18 restores the 12 ``qcom,mdp-settings`` entries from the matching factory
DTB after successful MDP clock enable on every runtime resume, restricted
to ``qcom,msm8992-mdp5``. Vendor offsets use the MDSS base, so each is
translated by subtracting the 0x1000 MDP core offset. These are the panic/
robust LUT, bus and clock-control defaults that the vendor reapplies and
mainline previously left to firmware. This closes a confirmed initialization
gap; whether it resolves the underrun is not yet established. Core clock
remains at the phone-verified 200 MHz; interconnect support is still absent.

CRTC atomic debug state now includes a software underrun counter. The DRM
test helper saves passive live state at 2 and 5 seconds into
``state-live-2s.txt`` and ``state-live-5s.txt`` and prints both counters on
exit. Keep the test framebuffer active for at least 5 seconds to compare
them. Any underrun still causes test status 1; errors are not suppressed
and backlight stays off pending scanout verification.

V18's phone log confirms the factory-settings restore and PLL lock, but
again reports an initial INTF1 underrun. It removes FB 89 only about 17 ms
after enabling the output. Thus its 2/5-second counters (both 1) were sampled
after removal of the test framebuffer and cannot establish sustained scanout.
An early newline or EOF is a possible explanation; the transcript does not
identify the input event that ended modetest. Repeated counter lines can
also come from debugfs aliases rather than additional CRTCs or underruns.

V19 adds ``libra-drm-test hold CONNECTOR CRTC``. It supplies modetest with
a private input pipe and a newline after 8 seconds, independent of queued
ACM input. Live snapshots resolve debugfs aliases once and report the target
CRTC's active flag, a framebuffer attached to its planes and its underrun
counter. A sample without an active CRTC, attached framebuffer or counter
is rejected. Both interactive and timed tests retain kernel-error detection.
This version changes only userspace diagnostics; kernel/hardware settings
remain V18 and no backlight increase is automatic.

The logger creates missing capture-directory parents before starting its
child command. A direct hold after driver loading therefore works without
first running scan to create ``/run/libra-drm``. On an older initrd, run
``mkdir -p /run/libra-drm`` before the logger command. Failure to open the
capture file occurs before the child starts and does not request a modeset.

The V19 timed phone test keeps FB 89 active for about 7.8 seconds after
video enable. Its 2/5-second samples both show active=1, framebuffer present
and underrun_count=1, with successful vblank-driven cleanup. This verifies
valid samples and no growth of the observed startup underrun count; it does
not yet establish visible output or hardware frame progression.

V20 changes MSM8992 video enable to commit accumulated pipe/mixer/INTF
flushes before writing timing-engine enable, matching the vendor's
``mdss_mdp_display_commit()`` / ``mdss_mdp_video_display()`` order. Other
SoCs retain the original order. A marker logs flush status and the prior
timing-engine state. This is a targeted test of the startup underrun; its
effect is confirmed by the timed V20 phone test below; no IRQ error is suppressed.
The existing initialization already disables firmware timing engines.

Atomic debug state also records hardware frame/line counters only for an
active video interface when ``pm_runtime_get_if_in_use()`` can take an
existing power reference. It never wakes a suspended device or invokes
clock rate callbacks, and balances the reference after the reads. Timed
samples require frame-counter availability and report the modulo-32-bit
frame delta between 2 and 5 seconds; a zero delta fails the test. Start-order
and PM-guard mocks pass. Backlight remains zero during these tests.

The V20 phone transcript confirms flush=0x40020840 before enabling INTF1,
whose timing engine was zero. PLL locks at status 0xf5; both live samples
are active with FB 89 attached, underrun_count=0 and frame counts 109/290.
The 181-frame delta over roughly 3 seconds is consistent with 60 Hz. RMFB
cleanup completes with vblank and no timeout; the helper returns zero.
The startup underrun is absent in this run. This establishes controller
frame progression with backlight off; visible panel output is still pending.

After such a successful dark test, perform a short low-brightness visual
check in the same boot. Keep the timed pattern active and set WLED brightness
to 64 (of its 4095 maximum) only between seconds 2 and 5, restoring zero
afterwards. Verify the actual pattern, colors, stability and USB interaction
before using higher brightness or enabling automatic display startup.

The V20 short-brightness test still advances by 182 frames with no underrun,
but the user reports that the screen did not light. It warns about an
unbalanced IRQ enable in ``wled_ovp_work()``. The old helper returned zero
because its failure pattern missed WARN reports; this is not a successful
visual test.

V21 synchronizes WLED's software on/off state from MOD_EN after setup and
before IRQ configuration. A nonzero seed is used for an enabled module even
when default-brightness is zero, then the requested default is applied via
backlight_update_status(). IRQ setup and brightness transitions thus agree,
and a zero request actually disables the firmware-enabled module. This
adapts the upstream discussion of the same problem (not a claim that the
proposal is merged):
https://www.mail-archive.com/linux-kernel@vger.kernel.org/msg2658247.html

WLED actual_brightness now reads the programmed first enabled string or
selected modulator, with module-off detection and error propagation. The
WLED4 path with matching firmware sinks also applies the configured CABC
setting instead of returning before that write. Whether inherited CABC
gating explains the dark backlight is not established by this driver change.
Probe stores the WLED object for remove,
which cancels delayed work and stops valid IRQs before destroying the mutex.

The ``preview CONNECTOR CRTC`` action holds the pattern for 8 seconds and
gates low-brightness illumination on a valid zero-underrun 2-second sample
and no new kernel warning/error. It prints requested/actual brightness,
power and maximum, requires actual_brightness=64, and restores zero at 5
seconds or on interruption/failure. WARN and IRQ-imbalance reports now fail
both timed and interactive tests; they are not filtered away. Handoff,
on/off/cancel, CABC and readback mocks pass, as do preview gating, blackout
and new-warning classification scenarios. The V21 phone result follows.

The V21 phone test confirms firmware MOD_EN=0x80 is brought to requested/
actual brightness zero at probe, followed by requested/actual=64 and
bl_power=0 in preview. No IRQ-imbalance warning is present; live samples
have zero underruns and advance by 186 frames. The screen still does not
light. Crucially, the probe marker reports CABC=1: ``pmi8994.dtsi`` supplies
``qcom,cabc`` and the board had not deleted this inherited boolean. V21
fixed the missing write path but therefore still programmed CABC enabled.

V22 deletes ``qcom,cabc`` in the Libra board WLED node so the driver uses
direct software brightness rather than requiring the panel CABC signal.
Compiled-DTB checks require this boolean to be absent in all Libra variants;
the next phone marker must report CABC=0. No DRM, PLL, voltage, current,
PFET or IRQ configuration is changed in this experiment. Whether disabling
CABC restores illumination remains to be tested; programmed brightness
readback alone does not establish emitted light or a valid panel image.

The V22 phone marker confirms CABC=0, preview brightness reads back 64,
both samples have zero underruns and hardware frame counts advance by 187.
The user still reports no illumination. Thus disabling CABC does not resolve
the observed dark panel, and the test's zero exit only covers controller
progression, programmed brightness and absence of detected kernel errors.

V23 adds read-only ``firmware_state`` and ``hardware_state`` attributes on
WLED4 devices. The former preserves a bounded set of documented control,
sink and enabled-string registers before setup; the latter reads the same
registers under the WLED mutex. Per-register bus errors are explicit. Preview
prints both snapshots beside brightness readback, so MOD_EN, sink enable,
modulator/gate, CABC, dimming, PFET and fault states can be compared without
scanning unrelated PMIC blocks or writing diagnostic registers. Existing
power, current, frequency, brightness and DRM behavior is retained. Register
scope/error/buffer-bound mocks and handoff tests pass. Runtime register
evidence and a visible panel image are still pending.

The supplied V23 ``dmesg.txt`` exposes a diagnostic formatting bug:
``sysfs_emit_at()`` was used with the ordinary devm-allocated firmware
buffer, whose address was not page aligned. The kernel rejects that buffer,
producing a WARN for every attempted line and leaving firmware_state empty.
The live sysfs-buffer snapshot is populated: MOD_EN=0x80, sinks=0x30,
both string modulators=0x80, CABC=0 and brightness=0x40 on both strings.
Known OVP/ILIM/short bits are clear in status 0x08; the meaning of its bit 3
has not been established. SYNC reads 0x0f and switching-frequency register
0x8f. These values do not yet explain the absent illumination.

V24 uses bounded scnprintf() with an explicit capacity for the shared
formatter, supporting both an ordinary buffer and a sysfs show buffer.
Tests use unaligned buffers, short capacities and canaries and retain
register-scope/error/lock checks. Per-stage raw kmsg records now detect WARN
reports even if modprobe returns zero; preview refuses an empty firmware
snapshot. The display/backlight configuration is unchanged. Obtain the
firmware and post-probe snapshots before further illumination tests.

The V24 phone snapshots are populated without the formatter warnings.
Before setup, module enable is 0x80, sinks 0x30, both modulators 0x80,
brightness 0x0666, CABC bits 0x80 and SYNC 0x00. After setup, module enable
is zero as requested by the dark default; CABC bits are zero, short
protection changes from 0x02 to 0x82 and PFET TEST1 from 0x00 to 0x09.
The vendor also programs the latter two settings when its short IRQ exists,
so this evidence does not justify removing protection or PFET control.
No illumination is expected from the two-stage, requested-zero test.

The vendor brightness operation finishes with full-byte SYNC writes
0x0f then 0x00. Mainline's shared operation instead finishes with zero
then mask; the previous illuminated-register snapshot reads SYNC=0x0f.
V25 selects the vendor pulse only for Xiaomi Libra with PMI8994 WLED,
preserving the other devices' existing operation. It propagates either
write error and changes no current, voltage, frequency, dimming, PFET,
short/OVP protection or display setting. This is a targeted latching test,
not proof that the synchronization difference causes the black screen.
The next preview must leave SYNC at zero and still maintain valid frame
progression; actual illumination must be observed separately.

V26 complete WLED initialization and DSI checkerboard
--------------------------------------------------

The complete ``qpnp_wled_config()`` was compared with the generic
``wled4_setup()`` and its helper/probe writes, rather than only its first
three boost settings. The new supplemental DT properties select a complete
PMI8994 initialization path. Properties absent keeps the legacy path.
All masked writes preserve unrelated fields and report bus errors; the
matching-sink shortcut cannot skip the complete setup.

.. list-table:: Register comparison for the Libra LCD profile
   :header-rows: 1
   :widths: 18 40 42

   * - Register
     - Vendor operation / board value
     - Generic path before V26 / V26 coverage
   * - CTRL 0x44
     - LCD selection, bit 7 clear
     - Missing / explicit masked write
   * - CTRL 0x48
     - Feedback AUTO, low three bits = 0
     - Only optional autodetection writes / explicit setup write
   * - CTRL 0x49
     - VREF 350 mV, low nibble = 2
     - Missing / DT-driven masked write
   * - CTRL 0x4e
     - ILIM encoding 3; override bit when changing encoding
     - Low-field update / vendor conditional override implemented
   * - CTRL 0x4b
     - Board DT 26 ns, low two bits = 0
     - Missing / DT-driven masked write
   * - CTRL 0x4c
     - Vendor 600 kHz input falls back to code 11 (800 kHz)
     - Code 15 for literal 600 kHz / retained intentionally
   * - CTRL 0x4d
     - OVP 29500 mV, low two bits = 1
     - Covered / explicit masked write
   * - SINK 0x4a
     - Modulation + accumulator clocks, stagger, resolution, dim mode
     - Missing / DT 9600 kHz, stagger, 12-bit hybrid => 0x6c
   * - SINK 0x4b
     - Hybrid threshold 625 => code 3
     - Missing / DT-driven masked write
   * - SINK 0xd0, 0xe6
     - Secure unlock, TEST5 hybrid/analog 0x14 or digital 0x1e
     - Missing / covered
   * - SINK 0x46
     - Disable sinks, then enable strings 0/1 => 0x10, 0x30
     - Covered only after mismatch / always configured in complete path
   * - SINK 0x50, 0x60
     - Modulator enable + gate-drive bit for selected dim mode
     - Enable only / both fields configured
   * - SINK 0x51, 0x61
     - Synchronization delay 800 us => code 4
     - Missing / DT-driven masked writes
   * - SINK 0x52, 0x62
     - Full-scale string current 20000 uA => code 8
     - Covered only after mismatch / explicit masked writes
   * - SINK 0x56, 0x66
     - CABC enable bit; factory enabled, Linux deliberately disables it
     - Covered by helper / keeps the direct-brightness policy
   * - CTRL 0x5e
     - Short protection enabled with the short IRQ
     - Already handled by probe / retained
   * - CTRL 0xd0, 0xe2
     - Secure unlock + external PFET DTEST2 value 0x09
     - Covered / retained
   * - SINK 0x47
     - Brightness SYNC pulse 0x0f then 0x00
     - V25 already covers this / also used after complete setup
   * - CTRL 0x46
     - Module output enable managed outside vendor config
     - V26 quiesces output before setup; requested brightness enables it later

The three requested board properties are ``qcom,fdbk-output = "auto"``,
``qcom,vref-mv = <350>`` and ``qcom,boost-duty-ns = <26>``. The factory DT
overrides the vendor driver's generic 104 ns default with 26 ns; vendor
integer encoding gives 26/52 = 0. Thus register zero is a valid board
encoding and does not establish a zero boost-duty budget. Modulation,
hybrid threshold, synchronization delay and phase properties also come
from the selected factory DT. These properties have schema/driver range
checks. 9-bit resolution, when requested, limits brightness to 511.

The 600 kHz frequency exception preserves the actual firmware code 15 and
the mainline property's units instead of copying the vendor parser's
fallback. The complete path keeps module output off until backlight core
applies the requested brightness, avoiding transient firmware-level light.
Comparison mocks use both clean and dirty register seeds and compare all
23 vendor initialization register fields, including short/PFET probe setup.
Every one of 44 bus-access failure points propagates its error. The compare
accounts explicitly for output-off, frequency and native CABC policy.

The existing host generator is reachable only through an unused manager
wrapper. V26 adds a Libra-only ``test_pattern`` sysfs control on the DSI
controller. Enabling requires a powered, enabled video host and is serialized
with host state and command transfers. It uses the existing RGB24 checkerboard
setup and checks the enable-bit readback. Disable/reset/power-off clears the
generator; unpowered disable performs no MMIO and unpowered enable returns
EPIPE. It does not runtime-resume an unpowered provider.

``libra-drm-test dsi-pattern CONNECTOR CRTC`` initializes the normal mode,
then selects the host checkerboard before the three-second low-brightness
window. MDP pixel scanout is bypassed; display mode, clocks, PHY and panel
initialization are still required. Cleanup disables the generator and
backlight before the timed test exits. Compare this with ``preview`` using
the same mode and brightness to distinguish the pixel-source path from
DSI/panel/backlight behavior. Guard, generated-register, readback-failure
and timed-cleanup mocks pass. Neither test has been visually confirmed on
the phone yet.

V26 phone results and V27 diagnostics
------------------------------------

The V26 phone runs confirm complete WLED setup and register readback:
module 0x80, sinks 0x30, both modulators 0x80, modulation control 0x6c,
CABC zero and brightness 0x0040. Normal preview has zero MDP underruns
and 187 hardware frames between its live samples. The user observes no
backlight glow or visible image. Programming and MDP frame progression
therefore do not establish physical backlight or panel operation.

The live DSI checkerboard switch produces ``dsi_err_worker: status=5``
on both enable and disable. This is the driver's TIMEOUT (0x1) and FIFO
(0x4) state combination. V26's helper missed this message and returned
zero; that run must be treated as failed, and cannot exclude the DSI path.
V27 includes worker errors in the failure classifier and logs the raw
TIMEOUT_STATUS and FIFO_STATUS values before the existing acknowledgement
writes. It does not suppress or clear additional errors. Live generator
switching remains unverified and should not be repeated to diagnose the
absent backlight until the raw error is understood.

V27 adds ``libra-drm-test backlight`` to isolate WLED from native display
initialization. On a fresh late-load boot, load bias and backlight, then run
this test before panel/framebuffer release/MSM. It refuses a loaded MSM
module, requests 512/4095 for three seconds, records live register/readback
state and new kernel messages, then restores zero on completion or signal.
The exit status reports programming/error/cleanup checks, never optical
success. This tests a more visible brightness than the previous 64/4095
preview while retaining the configured current, voltage, PFET protection,
frequency and dimming settings. Host script tests cover readback failure,
new DSI errors, the MSM guard and signal cleanup; hardware light remains
to be observed separately.

V28 native preview at the observed illumination level
-----------------------------------------------------

The user reports that V27's isolated 512/4095 WLED test illuminated the
screen for several seconds and made text readable. Turning off after the
three-second window is the helper's intentional cleanup. This establishes
physical backlight illumination and a readable image during the firmware
display stage, before native MSM or panel initialization. It does not
establish native MDP/DSI pixel output. The earlier 64/4095 preview did not
produce observable light; its black-screen result cannot by itself identify
a native panel failure.

V28 changes only normal ``preview`` to the same 512/4095 level. It retains
the live-scanout and kernel-error checks before illumination and the
three-second window/automatic blackout. Native driver, DT and WLED setup
are unchanged. The DSI generator test retains its previous brightness and
is still unverified because of the V26 switch-time errors.

On V28, after loading bias, backlight, panel, releasing the firmware
framebuffer and loading MSM, verify connector/CRTC IDs and run::

  libra-kmsg /run/libra-drm/preview-live.txt /usr/sbin/libra-drm-test preview 33 88

Record whether the native test pattern is visible, the screen merely
glows, or no light is observable. Visible text from the isolated test and
a visible native test pattern are different evidence.

V29 buffered monitoring after the native 512 preview
-----------------------------------------------------

The user repeated normal native preview on V27 with its brightness changed
to 512. No light was visible. The live WLED register readback contains
module 0x80 and 0x0200 brightness on both strings, and no new native display
error appears in the supplied log. The 2-second sample is valid with
framebuffer present and zero underruns. The nominal 5-second sample is
invalid: its framebuffer is absent, and its frame count is 815 rather than
109. The test removes its framebuffer at eight seconds. This invalid pair
must not be interpreted as 706 frames of active test-pattern progress or
as a proved controller failure.

The monitor printed its full WLED snapshot directly to ACM before sleeping
for the second sample. Host backpressure could delay that sample until
after framebuffer removal and also prolong the illumination window. V29
buffers the entire monitor's stdout/stderr in ``/run/libra-drm/monitor.txt``
and prints it after waiting for completion. It calculates frame progress
only when both live samples are valid. A test with an undrained output pipe
reproduces the late, detached framebuffer with the old monitor and keeps
the second sample attached with the new monitor; both restore zero.
This is a diagnostic scheduling fix, not a fix for the absent native light.
The next investigation compares saved GPIO and regulator state across
native panel initialization with the working firmware-display stage.

V30 pre-video panel power-mode readback
--------------------------------------

The supplied before/after snapshots show reset GPIO78 high and PM8994
GPIO14 high (normal mux, VIN2, push-pull) at both endpoints. LAB/IBB use
counts increase from zero to one with 5500 mV selectors; native DSI and PHY
consumers acquire L2, L12, L14 and L28 votes. These snapshots do not show
a forgotten supply enable or a reset held low. They are endpoint and
programmed-state observations, not rail voltage measurements or proof of
the reset pulse waveform. Duplicate direct-SPMI/RPM regulator names must
be interpreted together with their consumer/provider ownership.

DSI command DMA completion alone does not prove receipt by the panel.
V30 adds the opt-in, read-only module parameter ``read_power_mode`` to the
Libra panel driver (default false). The late-load helper supplies it as
``read_power_mode=1`` when loading the panel. After the unchanged initialization
commands and sleep-out delay, while the host is powered and video has not
yet been enabled, the panel sends one LP DCS GET_POWER_MODE (0x0a) read.
No video generator switch, GPIO sequence, voltage or WLED configuration
is changed. The existing MSM host handles the BTA/response transfer.

Exactly one response byte is required before reporting its raw value,
display-on, sleep-out and normal-mode bits. A failed, empty or oversized
response is reported separately, as is a response with display-on or
sleep-out clear. The diagnostic does not turn a read-path failure into a
panel-prepare failure and its cascading commit errors; the preview helper
detects the report and skips illumination. A failed read cannot by itself
distinguish a sleeping panel, an unsupported read or a broken receive path.
A valid reply supplies stronger evidence than the earlier TX-only logs.

Host tests cover LP message type/channel/payload/length, optional invocation
only after successful initialization, ready/not-ready replies, failed and
invalid lengths, unavailable transfer callbacks and original power/GPIO
error cleanup. Hardware reply remains to be collected on the phone.

V31 settled and active power-mode reads
---------------------------------------

V30 receives a one-byte DCS response: the raw readback word contains response
type 0x21 and data 0x0c, which the host decodes as display-on and normal-mode
set with sleep-out clear. There are no DSI timeout/FIFO reports around this
read. This is evidence of a working command/response transaction, but not
proof that every initialization write succeeded. The published DCS field
description in the `ST7789V datasheet, section 9.1.5
<https://dl.espressif.com/dl/schematics/ST7789V_SPEC_V1.0.pdf>`_ also defines
bit 4 as sleep-out; that document is used for the shared DCS field meaning,
not for an RSP61322-specific timing requirement.

The read was made about 50 ms after Sleep Out, before video start. V30
treated this early state as final and skipped the preview. Its monitor
then exited before taking the second sample; the missing 5-second sample
was not another controller failure. The earlier native 512 preview still
had no observable light, so an early-read policy fix alone does not
establish a working native display.

V31 retains the vendor commands, their order and their original delays.
With diagnostics enabled, a successful pre-video read with sleep-out clear
causes a further 100 ms settling wait and one ``settled`` read. Neither
pre-video value alone is treated as a final not-ready error. The new,
read-only panel ``power_mode`` attribute performs an LP DCS read while
the panel is prepared. It is exposed only with ``read_power_mode=1``;
unprepared reads return EPIPE without a transfer. Panel prepare/unprepare
and these reads share a mutex, and the MSM host serializes transfers with
disable/power-off using the same device-then-command lock order as TPG.

At the valid 2-second scanout sample, preview reads this attribute and
records the ``active`` result in ``panel-power-live.txt``. It requires both
display-on and sleep-out set, and checks new DSI/kernel failures, before
the three-second illumination window. A failed or not-ready active read
keeps the backlight off. Thus pre-video, settled and active observations
distinguish delayed settling from a state that changes only after video
starts or remains asleep. No wake command is retried and no GPIO, supply,
WLED or TPG setting is changed by this diagnostic. Early monitor exit is
reported explicitly; absent samples are not parsed or used for frame deltas.

Tests cover initial-asleep/settled-ready responses, active awake/asleep
responses, read lengths/errors, preparation guards and original rollback.
A concurrent host test holds power-off until a transfer completes.
The monitor test retains valid samples under blocked output and suppresses
illumination on an asleep or failed active read. Optical operation and
the actual V31 panel replies remain to be tested on the phone.

V32 explicit active-video Sleep Out tests
-----------------------------------------

V31 reads 0x0c at all three points: pre-video, after the additional 100 ms,
and after video has run for roughly two seconds. Each receives a one-byte
DCS response without a new timeout/FIFO report. The active CRTC still has
its framebuffer, zero underruns and 103 hardware frames at the first live
sample. This no longer supports the early-read-only explanation. The
monitor correctly leaves the backlight off and reports its early exit.

The downstream DCS short-write builder ignores the dummy second payload
byte for type 0x05. Both its ``11 00`` payload and mainline's one-byte
``11`` produce the MSM command word 0x80050011 for VC0/last packet.
Changing the nominal payload length would not change this wire header.
The firmware driver can also choose a panel using bootloader GCDB data,
whereas the supplied mainline command line contains no panel selection.
The factory default profile is evidence for the driver choice, not a
confirmed identification of the physical panel.

V32 exposes an explicit ``wake_test`` diagnostic only alongside the opt-in
power-mode attributes. It accepts ``lp`` or ``hs``, requires a prepared
panel and first reads ``wake-before``. An already-awake panel sends no
wake command. Otherwise it sends one standard DCS Sleep Out (0x11), waits
120 ms and reads ``wake-lp`` or ``wake-hs``. A failed transfer/read is
reported, and a valid reply still asleep returns EAGAIN. There are no
automatic retries, vendor-register writes or configuration changes.

``libra-drm-test wake-lp 33 88`` and ``wake-hs 33 88`` are explicit test
actions. They initialize the usual framebuffer, wait for a valid live
scanout sample, request the selected wake test, then use the existing
active-power-mode/error checks before the 512/4095 illumination window.
Normal ``preview`` does not request a wake test. Run LP first and use HS
if it remains asleep; an already-successful wake need not be repeated.

A separate read-only ``identity`` attribute performs one-byte LP reads
of registers 0xda, 0xdb and 0xdc on a prepared panel. It reports raw
``id_da``, ``id_db`` and ``id_dc`` bytes. Unsupported/invalid reads return
errors; unknown or zero IDs do not select a different profile. The helper
does not automatically query IDs. After the test, with the host still
powered, collect them if needed::

  cat /sys/bus/mipi-dsi/devices/fd994000.dsi.0/identity

Actual command-building tests verify LP/HS flags, the single wake message,
120 ms wait, no retry, already-awake behavior and read/write failures.
Identity tests verify guarded one-byte LP reads and early failure handling.
Monitor tests verify selected methods, wake failure keeps output at zero,
and buffered output still permits a valid second sample. These tests do
not establish that the phone will wake or identify its controller.

V33 re-audit of factory cold initialization
-------------------------------------------

Both V32 active-video wake tests still read 0x0c after their explicit Sleep
Out; ID reads return zero. This does not justify questioning the power-mode
response without new evidence or selecting a different panel from zero IDs.
The cold initialization path was compared with the selected factory DT and
the actual vendor call chain: LINK_READY -> mdss_dsi_on() ->
panel_power_on() -> PHY configuration and host setup -> link clocks ->
controller reset -> LP11 panel reset. UNBLANK then sends the panel's LP
command list before MDP starts video.

Reference files are mdss_dsi.c, mdss_dsi_host.c, msm_mdss_io_8974.c,
mdss_dsi_panel.c and the selected DTB's RSP61322 panel/controller nodes.
An independent compare extracts the binary DT's values and feeds the actual
mainline timing calculation and PHY-enable functions into an MMIO recorder.
Its profile is recorded in build/libra-v33-vendor-profile.json.

.. list-table:: Factory cold-init comparison
   :header-rows: 1
   :widths: 25 35 40

   * - Item
     - Selected factory behavior
     - Before V33 / resulting change
   * - Reset/init clock-lane state
     - LP11 init; force-clock-lane-hs absent, so no forced HS request
     - Mainline forced HS before reset / automatic clock operation;
       Libra host clears the inherited force-request bit
   * - GPIO78 drive
     - Active reset pin uses 8 mA
     - 2 mA / restored 8 mA
   * - PHY strength 0/1
     - 0x77 / 0x06; receive enable follows PHY enable
     - 0xff / 0x06, receive enabled earlier / factory values and order
   * - PHY global test control
     - Complete zero write for the single-DSI configuration
     - Masked update retaining other bits / complete zero for Libra
   * - Five lane blocks
     - All nine fields per lane written, including zero configuration,
       test-datapath and debug-selection fields
     - Several zero writes omitted / all 45 factory fields covered for Libra
   * - Twelve PHY timing registers
     - e1 4b 37 00 a9 ab 2a 4f 3d 03 04 00
     - Calculated values / factory table at the observed fixed-mode
       bit rate 843840000 Hz; other rates retain calculation
   * - CLK_PRE / CLK_POST
     - 0x2f / 0x19, no doubled-pre extension
     - Calculated values / factory values for the same fixed-rate profile
   * - CLK_ZERO extension
     - Explicit register write, including zero
     - Zero case omitted / always program the current extension bit
   * - 20 nm PHY regulator setup
     - Non-LDO values 03 03 03 00 20, CAL_PWR=01, LDO=00;
       TEST=07 property unused in the non-LDO path
     - Already equivalent / no change
   * - Panel reset waveform
     - High 5 ms, low 10 ms, high 10 ms after link setup
     - Equivalent active-low GPIO operations / no change
   * - On/off commands
     - Fourteen on and two off packets, LP on/HS off; display-on precedes
       sleep-out, whose wait is 50 ms
     - Packet types, normalized short payloads, bytes/order/delays match /
       no command change
   * - Cold-path diagnostic traffic
     - No intervening power reads or extra 100 ms settling wait
     - V30/V31 inserted these / removed from prepare; explicit diagnostics
       and the active preview read remain available
   * - Video flags / EOT / internal clocks
     - Burst RGB888, HSE disabled, LP BLLP, no TX EOT append, CLK_CTRL 0x23f
     - Equivalent / no change
   * - Bias readiness
     - Vendor checks LAB/IBB VREG_OK; generic enable checks control bits
       with fixed delays
     - Control-bit/delay-only path / regulator error flags expose VREG_OK
       and short state; panel waits for both outputs before GPIO/reset,
       with a bounded 100 ms timeout and rollback on failure

Fixed timings apply only to Xiaomi Libra with the MSM8992 20 nm PHY at the
mainline-rounded 1080p60 bit rate. The strength/lane profile is limited to
that board/PHY combination. Other boards retain existing programming and
other rates retain timing calculation. PLL, MDP startup flush, WLED and USB
settings are unchanged. This restores source-supported factory conditions;
it does not prove that a particular difference caused the black screen.

Tests compare all factory lane/timing values from dirty register state,
other-board/PHY/rate paths, extension-bit clearing and no writes for invalid
timing requests. Host tests exercise actual panel flags and the clock-lane
branch while preserving unrelated bits and other-device behavior. Panel
tests verify rollback and no automatic DCS read or settling delay. Bias
tests use the actual kernel poll macro to verify delayed readiness, read
failure, short fault, timeout and rollback before GPIO/commands. Disabled
outputs do not report undervoltage; enabled outputs without VREG_OK do.
On the phone, use normal preview after the five stages; no explicit wake test is
needed. An awake response and a visible native pattern remain the required
hardware evidence.

V34 normal preview without a live DCS read
------------------------------------------

The V33 phone run selects the factory PHY profile, completes panel
preparation without a bias-readiness failure, and reports power mode 0x1c
(display-on, sleep-out and normal-mode set). The first live sample has an
attached framebuffer, zero underruns and 109 hardware frames. The earlier
sleep-out failure has therefore changed after factory-init alignment.
This is not yet optical confirmation: the helper never enabled backlight.

During the helper's active-video power-mode read, the error IRQ reports
FIFO_STATUS=0x44441000 and TIMEOUT_STATUS=1. The former includes overflow
on all four HS lane FIFOs (0x44440000) and the ordinary LP-empty bit
(0x1000). These are real overflow flags, also recognized by the vendor's
FIFO handler, and are not suppressed. The errors occur in the read/BTA
transaction, after the valid initial scanout sample; whether they recur
without this extra transaction must be checked separately.

Normal factory display startup does not perform this periodic diagnostic
read. V34 removes the power-mode lookup/read from normal preview and keeps
the same V33 kernel and configuration. Preview still requires a valid,
zero-underrun live sample and no new kernel/display failure before its
three-second 512/4095 window. It also rejects the core's panel-prepare
failure report; real FIFO/timeout errors remain failure conditions.
Existing read/wake diagnostics remain explicit operations and are not
recommended for this normal-display test.

Script tests verify that normal preview never reads the power control,
including when it is absent or contains an old asleep value; explicit
wake actions retain their read checks. Injected FIFO and panel-prepare
errors still prevent illumination. Output backpressure does not delay
the live samples. On the phone, use a fresh V34 boot after the V33 overflow,
load the five stages and run normal preview only. The result still needs
valid second-sample frame progress and an observed native test pattern.

V34 native output confirmed on the phone
-----------------------------------------

The user confirms seeing the native modetest pattern after a fresh V34
boot and the five late-load stages. Both live samples have CRTC88 active,
the test framebuffer attached, valid counters and zero underruns. The
hardware frame count advances from 109 to 297 (188 frames between samples).
WLED requested/actual brightness is 512/4095, with module 0x80, sinks 0x30
and both string brightness registers 0x0200. The supplied log contains no
new DSI FIFO/timeout, PLL, vblank/commit or kernel-warning failure. The
helper returns zero and removes the test framebuffer cleanly at exit.

This is the first visual confirmation of the complete native
MDP5 -> DSI/PHY -> panel -> WLED output path at the selected 1080x1920-60
mode. V33 restored the factory cold-init conditions and observed sleep-out;
V34 removed the automatic active-video read that coincided with overflow.
The combined result is verified; the hardware tests do not isolate which
individual V33 setting resolved the earlier sleep-out failure. Explicit
active-video read/TPG diagnostics remain separate, unverified operations.

The verified image and its source-change snapshot are preserved under
build/verified-libra-drm-v34/, including SHA256SUMS and hardware-result.json.
The three-second illumination window and automatic blackout are intentional
helper behavior. This confirmation covers the basic native display mode,
not GPU acceleration, suspend/resume or arbitrary modes.

CPU support is limited to the legacy SCM/ACC **cold-boot** path for four A53
and two A57 cores. CPU preparation selects the 600 MHz GPLL0 auxiliary path;
the clock provider keeps that source enabled. Early SCM extended arguments
must not depend on the tzmem pool, which is created only at driver probe.
The companion cluster/CCI clock and cpufreq drivers now expose the full
factory frequency plans using CPR open-loop calibrated voltages. TSENS supplies
temperature readings and CPU cooling limits. Closed-loop CPR adaptation, CPU
hot-unplug, deep idle and suspend remain unsupported. See the Debian guide
for validation status and frequency/voltage coordination.
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
boot-libra-alpine-drm.img         Six-core simplefb boot, deferred native DRM
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
  cat /run/libra-drm/clk-counts-after.txt

Current images retain the firmware display at boot and leave native drivers unloaded.
First verify ACM and host ping to 192.168.7.2. Enable transcript logging in
the host serial terminal before loading any native driver. Over ACM, collect::

  cat /run/libra-status.txt
  cat /run/libra-usb.log
  dmesg

The late DRM image keeps the backlight off. A dark screen after backlight
driver binding is expected. Use ``hold`` to collect frame progression and
errors; ``preview`` checks live scanout and new kernel messages before
its timed illumination window. If abnormal illumination recurs while USB
is usable, shut down::

  for f in /sys/class/backlight/*/brightness; do echo 0 > "$f"; done
  poweroff -f

Load exactly one stage, then verify that ACM and host ping still work before
entering the next command::

  libra-drm-load bias
  libra-drm-load backlight
  libra-drm-load panel
  libra-drm-load release
  libra-drm-load msm

The release stage unbinds simpledrm without loading native drivers; the
screen may go dark. Check USB and report a failed release before proceeding.
The MSM stage probes the native MSM/DSI/PHY drivers with ``fbdev=0``.
A zero modprobe status does not
establish successful device binding. Inspect the streamed messages and
``/sys/kernel/debug/devices_deferred`` if no native DRM device appears.
Per-stage snapshots and raw ``*-live.txt`` records are in
``/run/libra-drm-load/`` while the phone is alive.
If USB stops, keep the host transcript and report the last stage/output;
further phone-side commands cannot be entered through the lost link.

Each stage writes a marker to pmsg when available. After a warm reboot into
simplefb, ``/sys/fs/pstore/`` may contain these markers and prior console
output if the bootloader preserved reserved RAM. This is a recovery aid,
not guaranteed storage across reboot or power loss.

After the modules are loaded and USB is still usable, run a resource scan,
verify USB again, then use its connector/CRTC IDs for the explicit modeset::

  libra-drm-test scan
  libra-kmsg /run/libra-drm/modeset-live.txt /usr/sbin/libra-drm-test hold CONNECTOR_ID CRTC_ID

The second command requests a 1080x1920 at 60 Hz test pattern and exits
automatically after its 8-second timer, streaming new kernel records through
the established USB terminal. It saves 2/5-second live samples and requires
an active CRTC with an attached framebuffer at each sample. Use ``modeset``
instead of ``hold`` for an interactive test that exits on Enter; wait at
least 5 seconds before pressing Enter, and avoid queued serial newlines.
The late image keeps its backlight at zero during the first test; a dark
screen is expected. Connector and CRTC IDs come from the scan output. Before/after logs
are saved under ``/run/libra-drm/``. Inspect ``modetest-scan.txt``, ``dmesg-after.txt``
and ``state-after.txt`` even if no display connector or modeset is available.

For a modeset test, use the connector and CRTC IDs reported by ``modetest``::

  modetest -M msm -s CONNECTOR_ID@CRTC_ID:1080x1920-60

If the native display goes dark but USB is alive, collect ``dmesg`` and DRM
state over ACM before rebooting. Current builds package only the six-core
simplefb and native DRM variants. Do not flash the test images over lk2nd or
invoke factory flash scripts. No factory images or phone partitions have
been modified by this build workflow.
