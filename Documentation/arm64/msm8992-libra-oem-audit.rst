=======================================
Libra OEM display sequence comparison
=======================================

Reference and scope
===================

The primary sources are the supplied read-only Xiaomi tree
``kernel_xiaomi_msm8992/`` and its selected DT captured in
``build/factory-libra-reference.dts``. This comparison describes the fixed
Sharp RSP61322 display path adapted to Linux DRM and clock/regulator APIs;
it is not a full downstream framework replacement.

Firmware panel and paired bias
==============================

The selected factory panel enables continuous splash. In
``drivers/video/msm/mdss/mdss_dsi_panel.c:mdss_dsi_panel_reset()``, firmware
handoff requests GPIOs but preserves their existing reset/enable outputs.
The DSI panel-initialized state suppresses on packets during successful
live handoff. The video transition has a separate non-handoff branch that
sends off packets, stops timing and later sends on packets.

The port adopts the initialized LCD only on explicit helper opt-in and
valid GPIO/bias state at first prepare. It takes normal regulator votes,
consumes this one-shot state and preserves the LCD without resetting it.
Native unprepare retains its normal ownership and later prepare uses the
factory cold sequence. PMIC GPIO direction comes from the pad state
populated from firmware MODE_CTL and maintained by pin configuration.

``drivers/regulator/qpnp-labibb-regulator.c`` recognizes coupling using
LAB_IBB_EN_RDY. Its paired enable/disable functions use IBB_ENABLE_CTL and
validate LAB_STATUS1 and IBB_STATUS1. For firmware-coupled PMI8994 only,
the port routes LAB enable ownership through IBB's command/mask/time.
Voltage/status/error fields remain per-rail. Paired SCP recovery checks
the common command; standalone and PMI8998 behavior retain their original
path. The port reads the coupling flag without rewriting mode or coupling.

The factory packet types, payloads, display-on-before-sleep-out order,
LP on/HS off states, 20/50 ms on delays and high/low/high 5/10/10 ms reset
waveform are preserved. The port sends HS shutdown packets in panel
disable before encoder timing stops, then resets/removes power in
unprepare. It does not leave DRM's prepared state stale after a command
error when hardware power-off succeeds.

Host, clocks and PLL
====================

``mdss_dsi.c:mdss_dsi_on()`` calls ``mdss_dsi_ctrl_setup()`` before enabling
link clocks and performing software reset. ``mdss_dsi_ctrl_setup()`` orders
mode/timing setup, host initialization and op-mode configuration. The port
applies that ordering only to the MSM8992 controller, including the factory
timing double-buffer enable/flush. Other host profiles keep their ordering.

The host's successful version read keeps regulator votes until initial
host power-on adopts them. Failed/abandoned probe releases them once.
MMCC byte/pixel rate updates enable their selected input only around the
RCG update and balance references on errors. Ordinary parent discovery
must not prepare a zero-rate PLL during provider registration.

``drivers/clk/qcom/mdss/mdss-dsi-20nm-pll-util.c`` performs initial lock
when no valid trim cache exists or the VCO rate changes. Successful lock
reads CORE_KVCO_CODE (0x168) and CORE_VCO_TUNE (0x160). Same-rate relock
uses the cached codes with the OEM overrides:

* KVCO_CODE (0x074): ``(code & 0x3f) | BIT(5)``;
* PLL_VCO_TUNE (0x0a8): ``(tune & 0x7f) | BIT(7)``;
* RESETSM_CNTRL (0x04c): 0xac;
* PLL_BKG_KVCO_CAL_EN (0x02c): 0x28.

The port uses its own hardware reads, invalidates the cache on failure,
and retains bounded lock polling and regulator/clock rollback. No measured
trim value is used as a constant.

Hardware evidence and cleanup
=============================

The v50 phone reported LAB_CTL=0, IBB_CTL=0x80, LAB_STATUS1=0xa0,
IBB_STATUS1=0x80 and LAB_IBB_EN_RDY=0x80. Both VREG_OK bits were present.
This confirms why the previous standalone LAB enable check was wrong for
that firmware state. GPIO checks passed, bias readiness changed from zero
to one, and panel preservation executed at 3.660182 seconds. The user saw
text after first-start handover. The transcript and matching image/source
are in ``build/verified-libra-drm-v50/``. This is one reported first boot;
it does not establish repeated-boot or native suspend/resume reliability.

V51 removes repeated firmware-state queries, success-path logs, raw bias
snapshots, timeout register dumps, the temporary MDP snapshot hook and
redundant boot-helper checks. The hardware programming sequences, one-shot
panel handoff, paired bias ownership, resource rollback and bounded waits
remain. Ten active software regressions are maintained in
``linux/tools/libra/tests/``; v51 phone validation is pending.

Simpledrm still releases clock/GDSC references before native registration,
and MSM still configures MDP, DSI, PHY and PLL. Full OEM live clock adoption,
MMSS_MISC clamp/ULPS ownership and dynamic refresh have not been ported.
Earlier failed candidates remain in the history archive rather than being
presented as hardware-validated fixes.
