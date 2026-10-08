Libra Adreno 418 bring-up
========================

The delivered rootfs starts GPU-accelerated Xfce X11 automatically after
USB readiness. Xorg Glamor and GLX use the real FD418 renderer, and GPU
textures use ordinary system pages rather than the 32MiB scanout arena.
The boot image defaults to ``msm.gpu=0`` and ``libra.gpu_defer=1`` so that
userspace prepares GPU providers before the first native MSM registration.
The new MSM8992 IOMMU and OCMEM drivers stop before accessing GPU hardware
until their ``msm8992_probe`` parameters are explicitly enabled. The image
continues to use the accepted CPU voltage profile and battery driver.

OEM references
--------------

* ``msm8992-gpu.dtsi`` and ``adreno-gpulist.h``: chip ID 0x04010800,
  512 KiB GMEM, a420 PM4/PFP microcode, 180/300/367/450/490/600 MHz plan.
  The initial table is limited to the factory 180 and 300 MHz entries.
* ``msm8992-iommu.dtsi``: secure device ID 18, nonsecure context 0 at
  0xfdb18000 serving stream IDs 0/1, SPI 241, 27 global BFB settings.
  Spare and secure contexts are not assigned to Linux.
* ``msm8992.dtsi`` and ``ocmem_core.c``: four OCMEM regions, 128 KiB
  macro size, register stride four bytes, graphics partition 0..512 KiB.
* PMI8994 S2/S3 supplies VDD_GFX. Linux votes the OEM initial RPM corner
  value 2 and uses the RPM graphics clock interface; no direct PMIC voltage
  writes or GPU undervolt profile are introduced. GX has CX as its parent.
* ``msm_iommu_sec.c`` initializes the firmware page-table pool even for
  nonsecure users. The driver sets the OEM 300 MiB virtual mapping limit
  before allocating the firmware-requested pool. The observed allocation
  is 148 KiB, not 300 MiB.
* Context ACTLR bits 28/29/30 follow the OEM L2 routing configuration and
  are restored after power collapse.
* Both microcode files are copied unchanged from ``system.img``
  ``/etc/firmware`` to ``/usr/lib/firmware/qcom``. They are not in boot.

Testing
-------

An existing userdata installation needs ``libra-gpu-update.tar.gz`` installed
before starting the matching boot. A freshly flashed companion rootfs already
contains it. The preceding battery boot is kept under
``build/archive/libra-battery-stable/``.

The normal desktop already activates MSM, so the manual first-load test
is only for a cold boot with ``/etc/libra/gpu-desktop`` set to 0. In that
mode the firmware console stays available while USB, Wi-Fi and SSH start.
Run the test from USB console or SSH::

    sudo libra-kmsg /run/libra-gpu-test.txt /usr/sbin/libra-gpu-test

The test refuses to run if MSM is already loaded or the kernel is tainted.
It manually probes OCMEM and the GPU IOMMU, loads the panel/backlight stages,
releases simpledrm and registers MSM once with GPU inclusion enabled.
The standalone probe opens renderD128 to trigger firmware loading and
CP_ME_INIT. Success requires GPU_ID=418, GMEM_SIZE=524288 and MAX_FREQ=300000000.
It starts LightDM after success. Failures before MSM registration can start
the software console; failures after registration preserve logs without
unloading or repeating GPU activation. Hardware faults require a clean boot.

The first live test on kernel #82 exposed older display teardown bugs before
any GPU hardware activation: stack-allocated bootstrap clocks retained by
devres, a missing fbdev IOVA unpin, per-DSI-packet IOVA pin leaks and VRAM
teardown before component buffers were freed. These ownership issues are
fixed. The test no longer depends on unloading the display module.

The firmware pool and IOMMU registration sequence subsequently passed on
the phone through a temporary diagnostic driver. Omitting the pool caused
secure-config ID 18 to return -EINVAL; initializing it allowed restoration
and context registration to succeed.

Rebinding the already registered GPU while software DRM was running then
made SSH unresponsive. No final stack trace was captured; that hang's cause
is not proven. Device rebinding is excluded from the shipped cold first-load
workflow. GPU ring and shader execution were still unvalidated at that stage.
Each test phase is now written to pmsg/ramoops, and context attachment logs
show progress before translation and IRQs are enabled.

Kernel #85 was confirmed clean with MSM absent and the firmware framebuffer
active. Its cold first-load test initialized OCMEM and the production IOMMU,
including the 148KiB firmware table and secure configuration ID 18. SSH then
became unresponsive during native MSM registration, before the scanout,
firmware/ring and shader test stages. No unload, rebinding or repeat attempt
was performed. The failure boundary is recorded in the host transcript;
After recovery, pstore identified an asynchronous SError in
``qcom_iommu_init_domain`` while programming the default translation domain.
The panic halted all CPUs, explaining the loss of both SSH and USB ACM.

The OEM QSMMUv1 register map has no TCR2 register at context offset 0x10.
The previous initialization and resume paths incorrectly accessed that v2
register and used the v2 TCR layout. MSM8992 now uses the OEM AArch32 TTBCR
layout (T0SZ relative to 32 address bits and EPD1 at bit 5), never accesses
TCR2, and restores the same saved configuration after power collapse. TCR
is programmed before TTBR, and context fault interrupts are enabled last.
The actual writer is tested against a v1 register map that rejects offset
0x10, with a separate v2 case preserving TCR2. This addresses the proven
register-map mismatch; successful GPU execution still needs a physical test.

The #86 phone test passed the previously fatal context programming and both
default/GPU domain attachments with kernel taint remaining zero. Component
binding then failed at OCMEM locking with -EIO. The upstream lock/unlock SCM
descriptors omitted the SIP owner, although availability was queried in the
SIP namespace. The OEM ``SCM_SIP_FNID`` uses owner 2; both descriptors now
use it. Failed allocation also returns the memory macros to CLK_OFF before
releasing allocation ownership. The GPU's simple_ondemand devfreq governor
and devfreq cooling support are enabled in the effective build configuration.
These changes require matching MSM/OCMEM modules as well as the new boot.

Kernel #87 passed OCMEM allocation, both IOMMU domain attachments, native
display registration and the firmware/ring probe on the phone with taint
zero. The first EGL test rejected software fallback because the Debian
loader still used the stock Gallium library. Mesa 25 links Gallium directly;
``LIBGL_DRIVERS_PATH`` alone does not select the private build. Debian also
uses its full package version for Gallium's SONAME and default symbol
versions. The private build now uses the same pinned Debian package version,
installs that SONAME link, and selects it through ``LD_LIBRARY_PATH`` scoped
to the GPU test. The default software desktop libraries are preserved.

The private EGL vendor is built alongside Gallium and selected by the
test's ``__EGL_VENDOR_LIBRARY_FILENAMES``. This avoids depending on the
stock EGL vendor's X11 loader symbols, which the minimal private Gallium
build does not contain. Both libraries are installed under
``/usr/lib/libra-gpu/dri`` with a scoped vendor JSON.

With that matched userspace installed online, the #87 phone reported
``GL_RENDERER=FD418`` and passed GLES2 shader compilation, triangle submission
and pixel readback: center RGBA 255/64/0/255, background 0/32/128/255. Five
further draws separated by one second of idle all passed, kernel taint stayed
zero and LightDM remained active. This validates the basic GPU/ring/GLES2
path; the desktop still uses llvmpipe and Xorg ShadowFB. X11/GLX acceleration
and longer stress/thermal validation have not been enabled or claimed.

Desktop rollout
---------------

The delivered rootfs enables ``/etc/libra/gpu-desktop=1``. After USB readiness,
the native-console service prepares OCMEM and the IOMMU before loading MSM
with GPU inclusion, so the desktop starts automatically. Disabling that file
retains the earlier deferred first-load test workflow.

Mesa now builds X11 and Wayland EGL, GLX, GBM and its separately loaded DRI
backend. The private GBM build uses its installed backend directory as the
compiled default, since LightDM's Xorg environment keeps LD_LIBRARY_PATH but
filters the other loader variables. A final Xfce session wrapper reapplies
the library paths after Xsession agents. Xfce stays on X11; no Wayland login
session is installed.

The live Xorg test enabled Glamor on FD418 and GLX reported accelerated
FD418 OpenGL 3.1. The user then observed block corruption and stale redraws.
Logs confirmed ENOSPC in GEM allocations and GL_OUT_OF_MEMORY for full-screen
FBOs: the running old MSM module put every GPU buffer in the 32MiB display
arena. The new allocation policy uses system pages for GPU-only buffers when
the GPU IOMMU is mapped, preserving contiguous scanout and DSI command DMA
buffers. Unsupported page-backed physical scanout is rejected without a
kernel warning. Software display was restored until the corrected module
could be activated by a cold restart.

The subsequent cold boot confirmed the new memory policy in the live GEM
dump: GPU ring/memptrs/texture objects use GPU address-space mappings, while
the DSI command buffer and scanout remain in the physical arena. Xorg enabled
Glamor on FD418, GLX reported FD418 with acceleration, kernel taint remained
zero, and neither allocation exhaustion nor GPU faults appeared in the boot
logs. The user reported normal display and a glmark2 result of 399 at 800x600.
The X11 refresh fix is verified for this reported test.

An isolated headless Wayland compositor reported FD418 and EGL Wayland,
dma-buf/modifier and explicit-sync capabilities. A real Wayland EGL client
rendered 194 frames in five seconds. These tests did not change the login
desktop. Further Wayland work is deferred at the user's request while X11
refresh is resolved.

The next test uses the separately installed Mesa 25.0.7 A418 driver from
``/usr/lib/libra-gpu/dri`` and requires the real ``FD418`` renderer. It compiles
vertex and fragment shaders, draws a triangle and reads back both triangle
and background pixels. Software fallback cannot satisfy its renderer check.
Debian's original Mesa remains installed for the default llvmpipe desktop.

Both unmodified Mesa 25.0.7 and the official 26.2.4 release device tables
list 405/420/430 but omit 418. The bundled patch adds the actual 418 ID to
the shared A4xx device information. It does not spoof the GPU as a 430.
Hardware support is a candidate until the phone passes the shader/readback
test; the host and existing phone's software rendering runs only validate
the harness and DRI ABI, not the GPU. ``btop`` and ``fastfetch`` are included
in fresh images and the offline update. PCIe Wi-Fi and
Bluetooth, touch, display, battery, CPU DVFS and thermal policy are unchanged.
