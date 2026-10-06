#!/usr/bin/env python3
"""Validate the matching ARM64 boot/initrd and sparse F2FS userdata delivery."""
import gzip
import hashlib
import importlib.util
from pathlib import Path
import stat
import struct
import subprocess

workspace = Path(__file__).resolve().parent.parent
build = workspace / "build"
spec = importlib.util.spec_from_file_location("legacy", workspace / "scripts/check-test-boot.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
legacy.check_dtb(build / "libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb")
stock = (workspace / "libra_images_6.1.7_20151221.0000.11_5.1_cn/images/boot.img").read_bytes()
boot = (build / "boot-libra-alpine-drm.img").read_bytes()
assert boot[:8] == b"ANDROID!"
fields = struct.unpack_from("<10I", boot, 8)
factory = struct.unpack_from("<10I", stock, 8)
assert all(fields[i] == factory[i] for i in (1, 3, 4, 5, 6, 7, 9))
page = fields[7]
start = page
payloads = []
for size in (fields[0], fields[2], fields[8]):
    payloads.append(boot[start:start + size])
    start += legacy.align(size, page)
kernel, initrd, table = payloads
assert kernel == (build / "libra/arch/arm64/boot/Image").read_bytes()
assert initrd == (build / "debian-libra-initrd.cpio.gz").read_bytes()
assert kernel[56:60] == b"ARM\x64"
assert struct.unpack_from("<4sII", table) == (b"QCDT", 3, 2)
expected = (build / "libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb").read_bytes()
for i, platform in enumerate((251, 252)):
    entry = struct.unpack_from("<10I", table, 12 + 40 * i)
    assert entry[:8] == (platform, 12, 0, 0, 65545, 65546, 0, 0)
    assert table[entry[8]:entry[8] + len(expected)] == expected
digest = hashlib.sha1()
for blob in (kernel, initrd, b"", table):
    digest.update(blob)
    digest.update(struct.pack("<I", len(blob)))
assert boot[576:596] == digest.digest()
cmdline = boot[64:576].split(b"\0", 1)[0].decode().split()
for option in ("rdinit=/init", "root=PARTLABEL=userdata", "rootfstype=f2fs", "msm.fbdev=1",
               "libra.drm_native=1", "libra.drm_auto=1", "consoleblank=0"):
    assert option in cmdline, option
assert not any(x.startswith("drm.debug=") for x in cmdline)
config = (build / "libra/.config").read_text().splitlines()
for option in ("F2FS_FS", "SECCOMP", "SECCOMP_FILTER", "TMPFS_POSIX_ACL", "USER_NS",
               "USB_CONFIGFS_ACM", "USB_CONFIGFS_NCM", "INPUT_EVDEV"):
    assert f"CONFIG_{option}=y" in config, option
data = gzip.decompress(initrd)
pos = 0
entries = {}
while pos < len(data):
    assert data[pos:pos + 6] == b"070701"
    values = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
    size, namesize = values[6], values[11]
    name = data[pos + 110:pos + 110 + namesize - 1].decode()
    if name == "TRAILER!!!":
        break
    content = legacy.align(pos + 110 + namesize, 4)
    entries[name] = (values, data[content:content + size])
    pos = legacy.align(content + size, 4)
assert entries["init"][1] == (workspace / "scripts/debian-init.sh").read_bytes()
assert stat.S_ISCHR(entries["dev/console"][0][1])
assert entries["dev/console"][0][9:11] == [5, 1]
assert entries["usr/sbin/libra-usb-gadget"][1] == (workspace / "linux/tools/libra/debian/usr/sbin/libra-usb-gadget").read_bytes()
for name in ("bin/busybox", "usr/sbin/blkid", "usr/sbin/resize.f2fs", "lib/ld-linux-aarch64.so.1"):
    binary = entries[name][1]
    assert binary[:5] == b"\x7fELF\x02" and binary[18:20] == b"\xb7\x00", name
bb = entries["bin/busybox"][1]
offset = struct.unpack_from("<Q", bb, 32)[0]
size, count = struct.unpack_from("<HH", bb, 54)
assert all(struct.unpack_from("<I", bb, offset + i * size)[0] != 3 for i in range(count))
print(f"PASS legacy Qualcomm boot, exact kernel/DTB, ARM64 glibc initrd ({len(initrd)} bytes)")

raw = build / "debian-trixie-arm64.f2fs.img"
sparse = build / "rootfs-libra-debian.img"
with sparse.open("rb") as file:
    header = struct.unpack("<IHHHHIIII", file.read(28))
assert header[0] == 0xED26FF3A and header[1] == 1
assert header[5] * header[6] == raw.stat().st_size
roundtrip = build / "debian-sparse-roundtrip.img"
try:
    subprocess.run(["simg2img", str(sparse), str(roundtrip)], check=True)
    def sha(path):
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()
    assert sha(raw) == sha(roundtrip), "sparse userdata round-trip mismatch"
    with roundtrip.open("rb") as file:
        file.seek(1024)
        assert file.read(4) == b"\x10\x20\xf5\xf2", "not a full F2FS image"
finally:
    roundtrip.unlink(missing_ok=True)
print(f"PASS fastboot sparse userdata: exact {raw.stat().st_size}-byte F2FS round-trip")
