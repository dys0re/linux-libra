====================================
Xiaomi Mi 4C / MSM8992 native display
====================================

Status
======

V50 successfully handed the firmware console over to native MSM DRM on
one reported phone boot. The user saw text immediately after handover.
The exact image, matching source, tests and user transcript are preserved
in ``build/verified-libra-drm-v50/``. V51 removes temporary diagnostics and
redundant checks; its software checks pass, but its image has not yet been
tested on the phone. Repeated cold boots and native suspend/resume are not
covered by the v50 result.

The boot image delivered to the user is always
``build/boot-libra-alpine-drm.img``. Versioned images are internal archives.
The selected factory DT and read-only Xiaomi source tree provide the panel,
bias, WLED, PHY and PLL reference. See :doc:`msm8992-libra-oem-audit` for the
adapted OEM paths and their integration limits.

Boot and handover
=================

Simpledrm owns the standard firmware framebuffer at 0x03400000:
1080x1920, RGB888, stride 3240. It holds the display clocks and GDSC until
explicit release. The legacy simplefb driver and separate late-load DT
variants are disabled/removed.

PID 1 configures USB ACM/NCM and its shell independently. After the USB
ready marker, a background display worker loads LAB/IBB, WLED and the
panel, releases simpledrm, then loads MSM with fbdev enabled. Releasing
simpledrm before PLL registration avoids active orphan-clock references.
The host keeps its version-probe supply votes until the first modeset
adopts them, with cleanup for failed or abandoned probe.

The panel helper requests firmware handoff only while simpledrm is bound.
The first panel prepare checks GPIO directions, deasserted reset, asserted
enable and live bias readiness once before acquiring normal bias votes.
It preserves a valid initialized panel without reset or on packets. An
unavailable state uses the factory cold sequence; the one-shot handoff
flag is consumed, so later prepares use that cold sequence. HS shutdown
packets are sent in panel disable before video timing stops; unprepare
then resets the LCD and removes bias power.

PMI8994's LAB_IBB_EN_RDY flag selects paired control through IBB_ENABLE_CTL.
Each output retains its own voltage and VREG_OK/error checks. The PMIC GPIO
provider reports the direction already populated from firmware. These are
required for correct handoff, not diagnostic overrides.

MSM exposes ``msmdrmfb`` and uses contiguous buffers from a 32 MiB VRAM
carveout. MDP5 can scan these buffers without an Adreno GPU. The console
helper checks an attached framebuffer, active CRTC, advancing hardware
frame count and no underruns before setting WLED brightness to 512/4095.
Those checks verify scanout/backlight programming; visible text remains a
hardware observation.

Build and boot
==============

Build incrementally for ARM64 without changing defconfig::

  sh scripts/build-libra.sh
  sh scripts/build-alpine-initrd.sh
  sh scripts/build-test-boot.sh
  python3 scripts/check-test-boot.py

The rootfs builder updates the dedicated Alpine F2FS image mounted at
``rootfs/``, installs matching modules and tools, packs the initrd and
unmounts it. It does not unpack a real rootfs into a workspace folder.
The boot checker verifies factory header/board selectors, DT, kernel,
initrd scripts and ARM64 modules against the current build.

On the host, use the same filename for each candidate::

  fastboot boot boot-libra-alpine-drm.img

``DRM_AUTO=0`` disables automatic loading and fbdev at packing time. Manual
stages remain available through the USB shell::

  libra-drm-load bias
  libra-drm-load backlight
  libra-drm-load panel
  libra-drm-load release
  libra-drm-load console
  libra-drm-test console

The default profile keeps the existing clock/power-domain ownership,
RPM skip-scaling option and MDP core rate of 200 MHz. V51 drops the forced
``drm.debug`` boot option and success-path bring-up messages. Normal driver
errors, bounded lock/readiness waits and resource rollback remain.

Diagnostics and regression checks
=================================

``/run/libra-drm-console.log`` records automatic startup. Per-stage live
kernel records are captured by ``libra-kmsg`` in ``/run/libra-drm-load/``.
``libra-drm-test`` supports scan, isolated backlight, console and timed or
interactive pattern tests. Discover connector/CRTC IDs with scan rather
than treating them as persistent identifiers.

The ``kms`` debugfs file retains the existing DSI and DRM state dump.
V51 removes the temporary five-block MDP snapshot extension and initial
bias/GPIO register logs. Do not use clk_summary as a passive snapshot:
it can resume clock providers.

Active regression sources are in ``linux/tools/libra/tests/``::

  python3 linux/tools/libra/tests/run.py

They compile actual driver callbacks against hardware/ownership models
and exercise handoff, paired bias, shutdown, PLL cache/rate/error behavior,
clock references, probe cleanup and the boot helpers. Generated harnesses
and executables go to ``build/validation/``. Historical failed candidates
and obsolete test sources are archived under ``build/archive/``; their
unused boot images are removed. Keep ``build/libra/`` for incremental
compilation and the verified v50 image for rollback.
