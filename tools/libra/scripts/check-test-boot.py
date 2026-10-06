#!/usr/bin/env python3
"""Read-only checks for legacy Qualcomm test boot images and the Alpine initrd."""
import gzip
import hashlib
import os
import stat
import struct
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
BUILD = WORKSPACE / "build"


def align(value, size):
    return (value + size - 1) // size * size


def check_dtb(path):
    def prop(node, name, kind="x"):
        value = subprocess.check_output(
            ["fdtget", "-t", kind, str(path), node, name], text=True).strip()
        return value if kind == "s" else [int(cell, 16) for cell in value.split()]

    mdss = "/soc/display-subsystem@fd900000"
    phy = mdss + "/phy@fd994300"
    clocks = prop("/soc/clock-controller@fd8c0000", "clocks")
    # The first four MMCC parents are XO (zero cells), GCC and two RPM clocks.
    expected = [0] * 5
    assert clocks[7:] == expected, "missing MMCC byte/pixel PLL parent wiring"
    assert prop(mdss, "status", "s") == "okay"
    assert prop(mdss, "clock-names", "s") == "iface bus vsync core", "missing SCM restore core clock"
    assert prop(phy, "status", "s") == "okay"
    children = subprocess.check_output(["fdtget", "-l", str(path), "/chosen"], text=True).splitlines()
    assert "framebuffer@3400000" in children, "missing simpledrm firmware framebuffer"
    firmware = "/chosen/framebuffer@3400000"
    assert prop(firmware, "status", "s") == "okay"
    assert prop(firmware, "compatible", "s") == "simple-framebuffer"
    assert prop(firmware, "reg") == [0, 0x3400000, 0, 1080 * 1920 * 3]
    assert prop(firmware, "width") == [1080] and prop(firmware, "height") == [1920]
    assert prop(firmware, "stride") == [1080 * 3]
    assert prop(firmware, "format", "s") == "r8g8b8"
    mmcc = prop("/soc/clock-controller@fd8c0000", "phandle")[0]
    assert prop(firmware, "clocks") == sum(([mmcc, index] for index in (20, 106, 23, 110, 24, 21, 26)), [])
    assert prop(firmware, "power-domains") == [mmcc, 5]
    for node in ("/soc/spmi@fc4cf000/pmic@3/labibb",
                 "/soc/spmi@fc4cf000/pmic@3/wled@d800"):
        assert prop(node, "status", "s") == "okay"
    backlight = "/soc/spmi@fc4cf000/pmic@3/wled@d800"
    for name, value in (("qcom,current-boost-limit", [620]),
                        ("qcom,current-limit-microamp", [20000]),
                        ("qcom,ovp-millivolt", [29500]),
                        ("qcom,switching-freq", [600]),
                        ("qcom,enabled-strings", [0, 1]),
                        ("qcom,vref-mv", [350]),
                        ("qcom,boost-duty-ns", [26]),
                        ("qcom,mod-freq-khz", [9600]),
                        ("qcom,hyb-thres", [625]),
                        ("qcom,sync-dly-us", [800])):
        assert prop(backlight, name) == value, f"WLED setting mismatch: {name}"
    assert prop(backlight, "qcom,fdbk-output", "s") == "auto"
    assert prop(backlight, "qcom,dim-mode", "s") == "hybrid"
    assert prop(backlight, "default-brightness") == [0], "unsafe probe-test backlight default"
    names = subprocess.check_output(["fdtget", "-p", str(path), backlight], text=True).splitlines()
    assert "qcom,en-phase-stag" in names, "missing factory phase staggering"
    assert "qcom,num-strings" not in names, "redundant WLED string configuration"
    assert "qcom,cabc" not in names, "WLED brightness is still gated by inherited CABC"
    ramoops = "/reserved-memory/ramoops@dfc00000"
    total = prop(ramoops, "reg")[-1]
    console = prop(ramoops, "console-size")[0]
    pmsg = prop(ramoops, "pmsg-size")[0]
    record = prop(ramoops, "record-size")[0]
    assert total - console - pmsg >= record, "no space for ramoops panic record"
    usb = "/soc/usb@f92f8800"
    core = usb + "/usb@f9200000"
    hsphy = "/soc/phy@f9b3a000"
    gcc = prop("/soc/clock-controller@fc400000", "phandle")[0]
    assert prop(usb, "compatible", "s") == "qcom,msm8992-dwc3 qcom,dwc3"
    assert prop(usb, "resets") == [gcc, 7], "missing USB30 controller reset"
    assert prop(hsphy, "resets") == [gcc, 6], "missing separate HS PHY reset"
    assert prop(usb, "assigned-clock-rates") == [19200000, 125000000]
    assert prop(usb, "clock-names", "s") == "core iface sleep mock_utmi xo"
    assert prop(usb, "interrupt-names", "s") == "pwr_event hs_phy_irq"
    assert prop(core, "snps,hsphy_interface", "s") == "utmi"
    assert prop(core, "phys") == [prop(hsphy, "phandle")[0]]
    assert prop(core, "clock-names", "s") == "ref suspend"
    assert prop(core, "clocks") == [gcc, 115, gcc, 138]
    properties = subprocess.check_output(["fdtget", "-p", str(path), core], text=True).splitlines()
    assert "snps,hsphy-interface" not in properties, "ignored UTMI property spelling"
    for quirk in ("snps,dis-clk-gating-quirk", "snps,gfladj-refclk-lpm-sel-quirk"):
        assert quirk in properties, f"missing {quirk}"
    print(f"{path.name}: display, MMCC PLL parents, ramoops, USB reset/clocks/quirks OK")


def check_ramdisk(blob):
    data = gzip.decompress(blob)
    pos = 0
    entries = {}
    while pos < len(data):
        assert data[pos:pos + 6] == b"070701", "invalid newc magic"
        fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16)
                  for i in range(13)]
        mode, size, major, minor, name_size = (
            fields[1], fields[6], fields[9], fields[10], fields[11])
        name = data[pos + 110:pos + 110 + name_size - 1].decode()
        start = align(pos + 110 + name_size, 4)
        if name == "TRAILER!!!":
            break
        entries[name.removeprefix("./")] = (mode, major, minor, data[start:start + size])
        pos = align(start + size, 4)
    assert entries["init"][0] & 0o111, "/init is not executable"
    console = entries["dev/console"]
    assert stat.S_ISCHR(console[0]) and console[1:3] == (5, 1)
    busybox = entries["bin/busybox"][3]
    assert busybox[:5] == b"\x7fELF\x02" and struct.unpack_from("<H", busybox, 18)[0] == 183
    for required in ("sbin/apk", "sbin/openrc", "sbin/getty", "usr/bin/setsid", "usr/bin/modetest",
                     "usr/sbin/libra-usb-gadget", "usr/sbin/libra-drm-test",
                     "usr/sbin/libra-drm-load", "usr/sbin/libra-drm-console", "usr/sbin/libra-kmsg", "sbin/modprobe"):
        assert required in entries, f"missing {required}"
    assert b"mount -t configfs" in entries["init"][3]
    assert b"setsid /sbin/getty -L -n -l /bin/sh 115200 tty1 linux" in entries["init"][3]
    assert entries["init"][3] == (WORKSPACE / "scripts/alpine-init.sh").read_bytes(), "stale init script"
    usb = entries["usr/sbin/libra-usb-gadget"]
    assert usb[0] & 0o111
    assert b'interface=$(cat "$ethernet/ifname")' in usb[3]
    assert b'network_mode=${2:-ncm}' in usb[3], "missing NCM default"
    assert usb[3] == (WORKSPACE / "scripts/alpine-usb-gadget.sh").read_bytes(), "stale USB helper"
    drm = entries["usr/sbin/libra-drm-test"]
    assert drm[0] & 0o111
    assert drm[3] == (WORKSPACE / "scripts/alpine-drm-test.sh").read_bytes(), "stale DRM helper"
    loader = entries["usr/sbin/libra-drm-load"]
    assert loader[0] & 0o111
    assert loader[3] == (WORKSPACE / "scripts/alpine-drm-load.sh").read_bytes(), "stale DRM loader"
    console = entries["usr/sbin/libra-drm-console"]
    assert console[0] & 0o111
    assert console[3] == (WORKSPACE / "scripts/alpine-drm-console.sh").read_bytes(), "stale native console helper"
    assert b"libra-usb-ready" in console[3], "native display may precede USB setup"
    assert b"libra.drm_auto=1" in entries["init"][3], "missing native console boot selection"
    reader = entries["usr/sbin/libra-kmsg"]
    assert reader[0] & 0o111
    assert reader[3] == (BUILD / "libra-kmsg").read_bytes(), "stale log reader"
    assert reader[3][:5] == b"\x7fELF\x02" and struct.unpack_from("<H", reader[3], 18)[0] == 183
    offset = struct.unpack_from("<Q", reader[3], 32)[0]
    size, count = struct.unpack_from("<HH", reader[3], 54)
    assert all(struct.unpack_from("<I", reader[3], offset + i * size)[0] != 3 for i in range(count)), "log reader needs a host libc interpreter"
    release = (BUILD / "libra-kernelrelease.txt").read_text().strip()
    for module in ("drivers/gpu/drm/msm/msm.ko",
                   "drivers/gpu/drm/panel/panel-sharp-libra-rsp61322.ko",
                   "drivers/regulator/qcom-labibb-regulator.ko",
                   "drivers/video/backlight/qcom-wled.ko"):
        packed = entries[f"lib/modules/{release}/kernel/{module}"][3]
        assert packed == (BUILD / "libra" / module).read_bytes(), f"stale module: {module}"
        assert packed[:5] == b"\x7fELF\x02" and struct.unpack_from("<H", packed, 18)[0] == 183
        assert f"vermagic={release} ".encode() in packed, f"module release mismatch: {module}"
    assert f"lib/modules/{release}/modules.dep" in entries
    print(f"Alpine initrd: {len(entries)} entries, ARM64 BusyBox/apk/OpenRC/modetest, console OK")


def check_boot(path, stock_header):
    data = path.read_bytes()
    assert data[:8] == b"ANDROID!"
    fields = struct.unpack_from("<10I", data, 8)
    for index in (1, 3, 4, 5, 6, 7, 9):
        assert fields[index] == stock_header[index], f"factory header mismatch: field {index}"
    page = fields[7]
    kernel_start = page
    ramdisk_start = page + align(fields[0], page)
    dt_start = ramdisk_start + align(fields[2], page)
    kernel = data[kernel_start:kernel_start + fields[0]]
    ramdisk = data[ramdisk_start:ramdisk_start + fields[2]]
    table = data[dt_start:dt_start + fields[8]]
    assert kernel == (BUILD / "libra/arch/arm64/boot/Image").read_bytes(), "stale kernel"
    assert ramdisk == (BUILD / "alpine-libra-initrd.cpio.gz").read_bytes(), "stale ramdisk"
    assert kernel[56:60] == b"ARM\x64"
    assert struct.unpack_from("<4sII", table) == (b"QCDT", 3, 2)
    for i, platform in enumerate((251, 252)):
        entry = struct.unpack_from("<10I", table, 12 + 40 * i)
        assert entry[:8] == (platform, 12, 0, 0, 65545, 65546, 0, 0)
        assert entry[8] % page == 0 and entry[9] % page == 0
        dtb = table[entry[8]:entry[8] + entry[9]]
        assert dtb[:4] == b"\xd0\x0d\xfe\xed"
        variant = "msm8992-xiaomi-libra"
        expected = (BUILD / f"libra/arch/arm64/boot/dts/qcom/{variant}.dtb").read_bytes()
        assert dtb[:len(expected)] == expected, "stale or mismatched DTB"
    digest = hashlib.sha1()
    for payload in (kernel, ramdisk, b"", table):
        digest.update(payload)
        digest.update(struct.pack("<I", len(payload)))
    assert data[576:596] == digest.digest(), "boot image ID mismatch"
    assert len(data) == dt_start + fields[8], "unexpected padding or footer"
    cmdline = data[64:576].split(b"\0", 1)[0]
    assert b"rdinit=/init" in cmdline
    skip_scaling = os.environ.get("RPM_SKIP_SCALING", "1")
    assert skip_scaling in ("0", "1"), "RPM_SKIP_SCALING must be 0 or 1"
    assert f"clk_smd_rpm.skip_scaling={skip_scaling}".encode() in cmdline.split(), "RPM scaling mode mismatch"
    assert b"maxcpus=1" not in cmdline, "unexpected single-core limit"
    auto = os.environ.get("DRM_AUTO", "1")
    assert auto in ("0", "1"), "DRM_AUTO must be 0 or 1"
    assert f"libra.drm_auto={auto}".encode() in cmdline.split()
    assert f"msm.fbdev={auto}".encode() in cmdline.split()
    assert b"libra.drm_late=1" not in cmdline.split()
    for option in (b"libra.drm_native=1", b"msm.mdp5_core_clk_rate=200000000",
                   b"log_buf_len=2M", b"loglevel=4", b"clk_ignore_unused", b"pd_ignore_unused"):
        assert option in cmdline.split(), f"Native display option missing: {option}"
    assert not any(option.startswith(b"drm.debug=") for option in cmdline.split()), "bring-up DRM trace enabled"
    assert b"ignore_loglevel" not in cmdline.split()
    print(f"{path.name}: factory header, payloads, QCDT selectors, SHA-1 ID OK")


def main():
    stock = (WORKSPACE / "libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img").read_bytes()
    stock_header = struct.unpack_from("<10I", stock, 8)
    check_dtb(BUILD / "libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb")
    config = (BUILD / "libra/.config").read_text().splitlines()
    assert "CONFIG_PROC_SYSCTL=y" in config, "missing kernel taint diagnostics"
    assert "CONFIG_BUG=y" in config, "missing clock WARN diagnostics"
    for option in ("CONFIG_DRM_MSM=m", "CONFIG_DRM_PANEL_SHARP_LIBRA_RSP61322=m",
                   "CONFIG_REGULATOR_QCOM_LABIBB=m", "CONFIG_BACKLIGHT_QCOM_WLED=m"):
        assert option in config, f"native-display driver is not deferred: {option}"
    for option in ("CONFIG_DRM_SIMPLEDRM=y", "CONFIG_DRM_FBDEV_EMULATION=y",
                   "CONFIG_FRAMEBUFFER_CONSOLE=y", "CONFIG_FB_DEVICE=y"):
        assert option in config, f"native framebuffer-console configuration mismatch: {option}"
    assert not any(line in config for line in ("CONFIG_FB_SIMPLE=y", "CONFIG_FB_SIMPLE=m")), "legacy simplefb enabled"
    check_ramdisk((BUILD / "alpine-libra-initrd.cpio.gz").read_bytes())
    check_boot(BUILD / "boot-libra-alpine-drm.img", stock_header)


if __name__ == "__main__":
    main()
