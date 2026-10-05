====================================
Xiaomi Mi 4C / MSM8992 native display
====================================

Status
======

The user reports five successful independent ``fastboot boot`` tests of
v34 and five of the v35 cleanup image. Each test restarted the phone and
loaded the native drivers; these were not repeated modesets within one
boot. The v35 cleanup therefore passed repeated boot regression for the
tested 1080x1920-60 native display path. Requested and actual WLED brightness
were 512/4095 in the captured previews, live framebuffers remained attached,
frame counters advanced and no new display errors appeared. USB ACM
remained usable. Six-core simplefb and Windows 11 USB NCM were verified in
earlier bring-up tests.

The cleanup removes temporary panel power/ID/wake and DSI TPG sysfs
interfaces, failed experimental actions, WLED register snapshots and
probe-progress logging. It retains the validated initialization,
clock/power error handling, bias readiness, IRQ balancing and modeset
checks. The repeated-boot v35 image and source checkpoint are preserved at
``build/verified-libra-drm-v35/``; v34 is retained at
``build/verified-libra-drm-v34/``.

Earlier tests of both v34 and v35 included a reported blank screen despite
passing software checks. A 12-second v34 observation had backlight without
pixels and 727 frames between the samples; another reboot produced a
visible pattern with the same frame progress. The cause of those earlier
observations remains undetermined. The later successful repetitions do
not erase them, but do not establish a cleanup-specific regression either.
The original v35 observation is retained at ``build/failed-libra-drm-v35/``
under its historical name.

A successful v34 active snapshot confirms video control 0x1f3, RGB888 burst
configuration 0x9230, factory video/PHY timing values, CLK_PRE/POST 0x192f,
PLL status 0xf5 and a disabled TPG. Timing double-buffer mode was zero;
visible output can work with that mode disabled. Selected values are
preserved in ``build/verified-libra-drm-v34/kms-success-selected.json``.
A same-version snapshot would help localize any future backlit-blank run.
A standalone nonzero status register does not prove a visible-output
failure; fresh error IRQ reports remain failures in the test helper.

The v36 timing-double-buffer source candidate is retained separately at
``build/candidate-libra-drm-v36/``; its unvalidated images were removed during
workspace cleanup. It is not part of the active cleanup source or rolling
boot images. Its enable/flush sequence follows the
factory ``qcom,timing-db-mode`` setting, but has no phone validation or
established causal link to the earlier blank observations.

The supported panel profile follows the selected factory DT's Sharp
RSP61322 video-mode configuration. Other Mi 4C panel profiles, dynamic
refresh, GPU acceleration, display IOMMU and suspend/resume are not
validated by this result. Native scanout uses contiguous buffers from the
MSM VRAM fallback. CPU support covers the six-core cold-boot path; DVFS,
CPR, hot-unplug and deep idle are not implemented.

The complete historical investigation and the factory comparison are
retained in :doc:`msm8992-libra-bringup`. History is not a current command
reference.

Effective initialization
========================

The primary references are the read-only workspace vendor kernel
``kernel_xiaomi_msm8992`` and the factory boot DTB selected for platform
251/252, board 12 and PMIC IDs 65545/65546. The display port restores:

* Secure MDSS configuration with the bus/core clocks active before native
  register access, and named MMCC parents for late-registered DSI clocks.
* A 200 MHz MDP core rate for this bring-up profile, and the factory MDP
  settings. Initial pipe/mixer/INTF flush is committed before starting the
  INTF1 timing engine.
* The 20 nm PLL0/auxiliary-PLL1 sequence, with 19.2 MHz reference and bounded
  calibration polling. The selected mode uses pixel clock 140640000 Hz,
  byte clock 105480000 Hz and bit clock 843840000 Hz.
* LP11 panel reset/init without a forced clock-lane HS request. GPIO78 uses
  the factory 8 mA drive and electrical high 5 ms, low 10 ms, high 10 ms.
* PHY strength 0x77/0x06, all 45 lane configuration fields and the factory
  timing bytes ``e1 4b 37 00 a9 ab 2a 4f 3d 03 04 00``. CLK_PRE/POST are
  0x2f/0x19 for this board/PHY at the fixed mode rate; other rates retain
  the timing calculation.
* LAB/IBB output readiness before GPIO reset and panel commands. Both
  VREG_OK conditions are checked with a bounded timeout; failures roll
  back the supply enables.
* The original 14 LP on commands and two HS off commands, including the
  vendor's display-on-before-sleep-out order and original delays.
* Complete PMI8994 WLED configuration and software/hardware handoff.
  The board uses two strings, feedback AUTO, VREF 350 mV, boost-duty 26 ns,
  modulation 9600 kHz, hybrid dimming and 800 us synchronization delay.
  CABC is disabled for direct brightness control. Register duty encoding
  zero represents the factory's 26 ns request, not a zero boost budget.

Normal preview performs no active-video DCS read. A former automatic
power-mode read returned an awake response but also caused HS FIFO overflow
and timeout reports during the transaction. The exposed experimental
interfaces have been removed; the kernel's pre-existing internal TPG
helper is not exported as a Libra user control.

Build
=====

Run from the workspace root, with this kernel checkout in ``linux/``::

  sh scripts/build-libra.sh
  sh scripts/build-alpine-initrd.sh
  sh scripts/build-test-boot.sh
  python3 scripts/check-test-boot.py

The workspace scripts and configuration are tracked in ``tools/libra/``.
Restore them into a fresh adjacent workspace before building::

  cp -a linux/tools/libra/scripts linux/tools/libra/cfg .

No defconfig is modified. Incremental builds reuse ``build/libra`` and build
only the three Libra DTBs (native, simplefb and late-load). F2FS support is
enabled. The builder checks requested configuration values against the
resulting config to catch silently discarded dependencies.

Workspace cleanup preserves the kernel/vendor checkouts, factory firmware,
``build/libra`` incremental outputs, the Alpine F2FS image and current build
inputs. User-provided logs/photos and the saved long-preview commands live
in ``evidence/``. Old bring-up logs and temporary test source are compressed
in ``build/archive/bringup-history.tar.gz``; the cleanup manifest is adjacent.
The retained v35 software checks live in ``build/validation/`` and run from
the workspace root. The historical failed-v35 directory keeps its original
observation/source and references the identical verified-v35 images instead
of storing another binary copy.

Alpine 3.24.2 aarch64 rootfs work uses the dedicated F2FS image mounted at
``rootfs/``. The builder verifies the minirootfs archive checksum, refuses
an occupied mount point, installs BusyBox/apk/OpenRC/libdrm modetest and the
matching modules/helpers, packs the initrd and unmounts. The phone boots a
RAM-only custom PID 1 and does not mount its eMMC. No SSH service is started;
USB ACM supplies the test shell.

Boot packaging uses the read-only factory input::

  libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img

Its legacy Qualcomm header has dt_size at byte 40 and a 4096-byte header
page. The output contains an ARM64 Image, gzip initrd and QCDT v3 data.
Factory load fields, platform/board/PMIC selectors and SHA-1 payload IDs
are preserved or recomputed by the packer. Use the existing lk2nd boot
workflow with these test images; the build does not flash phone partitions.

Outputs are ``build/boot-libra-alpine-drm.img`` and
``build/boot-libra-alpine-simplefb.img``. The validator checks all three DTBs,
ARM64 userspace/helpers/modules, exact initrd payloads and boot headers.
Generated images, tool environments and the vendor reference tree are not
stored in the kernel repository.

Normal late-load test
====================

Enable host serial transcript logging and verify ACM/NCM before loading
native drivers. Load one stage at a time, checking the host link after each::

  libra-drm-load bias
  libra-drm-load backlight
  libra-drm-load panel
  libra-drm-load release
  libra-drm-load msm

The backlight default is zero. The release stage unbinds the firmware
framebuffer separately; MSM then registers native DRM with fbdev disabled.
A zero module-insertion result is not proof of binding, so the stage helper
checks the WLED/native DRM device and reports fresh kernel faults. Logs
are saved in ``/run/libra-drm-load/``.

Scan resources, then use the returned connector and CRTC IDs::

  libra-drm-test scan
  libra-kmsg /run/libra-drm/preview-live.txt /usr/sbin/libra-drm-test preview 33 88

Preview holds the modetest framebuffer for eight seconds. At two seconds,
it checks active CRTC/framebuffer state, the hardware frame counter,
underruns and new kernel errors before requesting brightness 512/4095.
After its three-second illumination window it restores zero automatically.
A second live sample must retain the framebuffer and show advancing frames.
Monitor output is buffered so serial backpressure cannot delay the samples.

Supported helper actions are:

* ``scan``: resource listing without a modeset.
* ``hold CONNECTOR CRTC``: timed eight-second pattern with backlight off.
* ``modeset CONNECTOR CRTC``: interactive pattern; wait at least five seconds
  before pressing Enter so both live samples can be collected.
* ``preview CONNECTOR CRTC``: timed pattern with the bounded illumination
  window and automatic blackout.
* ``backlight``: isolated 512/4095 WLED test for three seconds, before MSM
  is loaded. Its status reports programming/readback/cleanup, while actual
  light remains a visual observation.

``libra-kmsg`` captures new raw records from /dev/kmsg while streaming a
readable serial transcript and preserves the child command's exit status.
Run logs live in ``/run/libra-drm/``. Do not use clk_summary for passive
snapshots: it can runtime-resume providers; the helper reads plain software
clock counters instead. Ramoops/pmsg provide a recovery aid if reserved RAM
survives a reboot, which is not guaranteed across bootloader or power loss.

Verification boundary
=====================

The v34 and v35 repeated boot tests cover basic native display initialization
and preview for the tested profile. Dynamic refresh, experimental controls,
GPU/IOMMU use and suspend/resume remain unvalidated. Earlier occasional
blank observations remain recorded without a proven cause. Software checks
alone cannot prove visible output, even when the test returns zero; the
user's visual result is part of hardware validation.
