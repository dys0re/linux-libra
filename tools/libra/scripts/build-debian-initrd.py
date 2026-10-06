#!/usr/bin/env python3
"""Pack a small ARM64 initrd; the real Debian root stays in its F2FS image."""
import gzip
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

workspace = Path(__file__).resolve().parent.parent
root = Path(sys.argv[1]).resolve()
build = workspace / "build"
entries = {}


def add(name, data=b"", mode=stat.S_IFREG | 0o755, major=0, minor=0):
    parent = Path(name).parent
    if str(parent) != ".":
        directory(str(parent))
    entries[name] = (mode, data, major, minor)


def directory(name):
    if name not in entries:
        add(name, mode=stat.S_IFDIR | 0o755)


busybox = (root / "usr/bin/busybox").read_bytes()
assert busybox[:5] == b"\x7fELF\x02" and busybox[18:20] == b"\xb7\x00"
add("bin/busybox", busybox)
applets = subprocess.check_output(["sudo", "-n", "chroot", str(root),
                                   "/usr/bin/busybox", "--list"], text=True).split()
for name in ("sh", "mount", "umount", "mkdir", "cat", "grep", "sleep", "ip", "touch", "ln",
             "setsid", "getty", "kill", "switch_root", "ls", "dmesg",
             "echo", "reboot", "poweroff", "sync", "ps", "tail", "awk", "vi"):
    assert name in applets, f"BusyBox needs {name}"
    add("bin/" + name, b"busybox", stat.S_IFLNK | 0o777)
add("init", (workspace / "scripts/debian-init.sh").read_bytes())
add("usr/sbin/libra-usb-gadget", (workspace / "linux/tools/libra/debian/usr/sbin/libra-usb-gadget").read_bytes())
for utility in ("resize.f2fs", "blkid"):
    add("usr/sbin/" + utility, (root / "usr/sbin" / utility).read_bytes())
    ldd = subprocess.check_output(["sudo", "-n", "chroot", str(root), "ldd", "/usr/sbin/" + utility], text=True)
    assert "not found" not in ldd, ldd
    for path in re.findall(r"(/[^\s()]+)", ldd):
        add(path.lstrip("/"), (root / path.lstrip("/")).read_bytes())
for name in ("sbin", "usr/bin", "proc", "sys", "run", "tmp", "newroot", "dev/pts"):
    directory(name)
add("dev/console", mode=stat.S_IFCHR | 0o600, major=5, minor=1)
add("dev/null", mode=stat.S_IFCHR | 0o666, major=1, minor=3)


def pad(data):
    return data + bytes((-len(data)) % 4)


cpio = bytearray()
for ino, (name, (mode, data, major, minor)) in enumerate(sorted(entries.items()), 1):
    name_bytes = name.encode() + b"\0"
    fields = (ino, mode, 0, 0, 1, 0, len(data), 0, 0, major, minor, len(name_bytes), 0)
    cpio.extend(pad(b"070701" + b"".join(f"{value:08x}".encode() for value in fields) + name_bytes))
    cpio.extend(pad(data))
name = b"TRAILER!!!\0"
fields = (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0)
cpio.extend(pad(b"070701" + b"".join(f"{value:08x}".encode() for value in fields) + name))
output = build / "debian-libra-initrd.cpio.gz"
output.write_bytes(gzip.compress(cpio, compresslevel=9, mtime=0))
print(f"{output}: {len(entries)} entries, {output.stat().st_size} bytes")
