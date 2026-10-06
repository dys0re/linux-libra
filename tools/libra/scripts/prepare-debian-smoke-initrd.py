#!/usr/bin/env python3
"""Test-only virtio modules around the delivered initrd's real userdata logic.

Requires a Debian generic ARM64 kernel unpacked in build/debian-smoke/kernel.
Never writes the delivery rootfs or boot image.
"""
import gzip
import lzma
from pathlib import Path
import stat
import struct
import subprocess

workspace = Path(__file__).resolve().parent.parent
build = workspace / "build"
stage = build / "debian-smoke"
release = "6.12.111+deb13-arm64"
data = gzip.decompress((build / "debian-libra-initrd.cpio.gz").read_bytes())
entries = {}
pos = 0
def align(n): return (n + 3) // 4 * 4
while pos < len(data):
    fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
    name = data[pos + 110:pos + 109 + fields[11]].decode()
    if name == "TRAILER!!!": break
    start = align(pos + 110 + fields[11])
    entries[name] = (fields[1], data[start:start + fields[6]], fields[9], fields[10])
    pos = align(start + fields[6])
entries["bin/insmod"] = (stat.S_IFLNK | 0o777, b"busybox", 0, 0)
entries["smoke-modules"] = (stat.S_IFDIR | 0o755, b"", 0, 0)
modules = []
for name in ("virtio_mmio", "virtio_blk", "virtio_gpu", "virtio_input", "evdev", "virtio_net", "f2fs"):
    deps = subprocess.check_output(["modprobe", "-d", str(stage / "kernel"), "-S", release,
                                    "--show-depends", name], text=True)
    for line in deps.splitlines():
        if line.startswith("insmod "):
            path = Path(line.split()[1])
            if path not in modules: modules.append(path)
commands = []
for i, path in enumerate(modules):
    target = f"smoke-modules/{i}.ko"
    content = path.read_bytes()
    if path.suffix == ".xz": content = lzma.decompress(content)
    entries[target] = (stat.S_IFREG | 0o644, content, 0, 0)
    commands.append(f"insmod /{target} || exec sh")
mode, init, major, minor = entries["init"]
# Load only virtio test hardware before using the identical userdata discovery,
# label check, offline resize and switch_root sequence from the delivery initrd.
init = init.replace(b"mount -t proc proc /proc", ("\n".join(commands) + "\nmount -t proc proc /proc").encode(), 1)
entries["init"] = (mode, init, major, minor)
entries["usr/sbin/libra-usb-gadget"] = (stat.S_IFREG | 0o755,
                                       b"#!/bin/sh\ntouch /run/libra-usb-ready\n", 0, 0)
result = bytearray()
for ino, (name, (mode, content, major, minor)) in enumerate(sorted(entries.items()), 1):
    name = name.encode() + b"\0"
    fields = (ino, mode, 0, 0, 1, 0, len(content), 0, 0, major, minor, len(name), 0)
    header = b"070701" + b"".join(f"{x:08x}".encode() for x in fields) + name
    result.extend(header + bytes(-len(header) % 4))
    result.extend(content + bytes(-len(content) % 4))
name = b"TRAILER!!!\0"
fields = (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0)
header = b"070701" + b"".join(f"{x:08x}".encode() for x in fields) + name
result.extend(header + bytes(-len(header) % 4))
(stage / "initrd.cpio.gz").write_bytes(gzip.compress(result, mtime=0))
print(f"Prepared test initrd with {len(modules)} virtio/generic modules")
