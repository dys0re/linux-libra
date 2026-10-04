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


def check_dtb(path, native):
    def prop(node, name, kind="x"):
        value = subprocess.check_output(
            ["fdtget", "-t", kind, str(path), node, name], text=True).strip()
        return value if kind == "s" else [int(cell, 16) for cell in value.split()]

    mdss = "/soc/display-subsystem@fd900000"
    phy = mdss + "/phy@fd994300"
    clocks = prop("/soc/clock-controller@fd8c0000", "clocks")
    phy_handle = prop(phy, "phandle")[0]
    # The first four MMCC parents are XO (zero cells), GCC and two RPM clocks.
    expected = [phy_handle, 1, phy_handle, 0, 0, 0, 0] if native else [0] * 5
    assert clocks[7:] == expected, "missing MMCC byte/pixel PLL parent wiring"
    assert prop(mdss, "status", "s") == ("okay" if native else "disabled")
    assert prop(phy, "status", "s") == ("okay" if native else "disabled")
    assert prop("/chosen/framebuffer@3400000", "status", "s") == (
        "disabled" if native else "okay")
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
                     "usr/sbin/libra-usb-gadget", "usr/sbin/libra-drm-test"):
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
        variant = "msm8992-xiaomi-libra" + ("" if "-drm" in path.name else "-simplefb")
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
    assert (b"libra.drm_test=1" in cmdline) == ("-drm" in path.name)
    assert (b"drm.debug=0x1ff" in cmdline) == ("-drm" in path.name)
    print(f"{path.name}: factory header, payloads, QCDT selectors, SHA-1 ID OK")


def main():
    stock = (WORKSPACE / "libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img").read_bytes()
    stock_header = struct.unpack_from("<10I", stock, 8)
    for native in (False, True):
        name = "msm8992-xiaomi-libra" + ("" if native else "-simplefb")
        check_dtb(BUILD / f"libra/arch/arm64/boot/dts/qcom/{name}.dtb", native)
    check_ramdisk((BUILD / "alpine-libra-initrd.cpio.gz").read_bytes())
    for variant in ("simplefb", "drm"):
        check_boot(BUILD / f"boot-libra-alpine-{variant}.img", stock_header)


if __name__ == "__main__":
    main()
