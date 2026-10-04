#!/usr/bin/env python3
"""Pack a test image in the legacy Qualcomm layout of the supplied stock boot.

Modern AOSP mkbootimg interprets Qualcomm's dt_size as header_version and
cannot reproduce this layout. Stock inputs are read-only; no signatures or
Android userspace arguments are copied to a modified test image.
"""
import argparse
import hashlib
import struct
from pathlib import Path


def align(value, page):
    return (value + page - 1) // page * page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("factory", "kernel", "ramdisk", "dtb", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cmdline", required=True)
    args = parser.parse_args()
    stock = args.factory.read_bytes()
    if stock[:8] != b"ANDROID!":
        raise ValueError("factory image has no Android boot magic")
    fields = list(struct.unpack_from("<10I", stock, 8))
    page = fields[7]
    if page not in (2048, 4096, 8192, 16384) or fields[4] != 0:
        raise ValueError("unsupported factory page size or second-stage image")
    dt_start = page + align(fields[0], page) + align(fields[2], page)
    dt_magic, version, count = struct.unpack_from("<4sII", stock, dt_start)
    if dt_magic != b"QCDT" or version != 3:
        raise ValueError("expected the factory QCDT v3 format")

    dtb = args.dtb.read_bytes()
    if dtb[:4] != b"\xd0\x0d\xfe\xed":
        raise ValueError("invalid DTB magic")
    if struct.unpack_from(">I", dtb, 4)[0] != len(dtb):
        raise ValueError("DTB size does not match its header")
    # MSM8992/Mi 4C keys verified against this factory table and our DTS.
    entries = []
    for i in range(count):
        entry = struct.unpack_from("<10I", stock, dt_start + 12 + i * 40)
        if entry[0] in (251, 252) and entry[1:4] == (12, 0, 0):
            if entry[4:8] != (65545, 65546, 0, 0):
                raise ValueError("unexpected factory PMIC IDs for Mi 4C")
            entries.append(entry[:8])
    if sorted(entry[0] for entry in entries) != [251, 252]:
        raise ValueError("factory table has no unique MSM8992/Mi 4C pair")
    dt_offset = align(12 + len(entries) * 40, page)
    dt_size = align(len(dtb), page)
    table = bytearray(struct.pack("<4sII", b"QCDT", 3, len(entries)))
    for entry in entries:
        table.extend(struct.pack("<10I", *entry, dt_offset, dt_size))
    table.extend(bytes(dt_offset - len(table)))
    table.extend(dtb)
    table.extend(bytes(dt_size - len(dtb)))

    kernel = args.kernel.read_bytes()
    ramdisk = args.ramdisk.read_bytes()
    if kernel[56:60] != b"ARM\x64":
        raise ValueError("kernel must be an uncompressed ARM64 Image")
    if ramdisk[:2] != b"\x1f\x8b":
        raise ValueError("ramdisk must be gzip-compressed")
    cmdline = args.cmdline.encode("ascii")
    if len(cmdline) >= 512:
        raise ValueError("legacy command line exceeds 511 bytes")
    fields[0], fields[2], fields[8] = len(kernel), len(ramdisk), len(table)
    digest = hashlib.sha1()
    for payload in (kernel, ramdisk, b"", table):
        digest.update(payload)
        digest.update(struct.pack("<I", len(payload)))
    header = bytearray(b"ANDROID!" + struct.pack("<10I", *fields))
    header.extend(stock[48:64])  # Original, empty board name.
    header.extend(cmdline.ljust(512, b"\0"))
    header.extend(digest.digest().ljust(32, b"\0"))
    header.extend(bytes(page - len(header)))
    with args.output.open("wb") as output:
        output.write(header)
        for payload in (kernel, ramdisk, table):
            output.write(payload)
            output.write(bytes(align(len(payload), page) - len(payload)))
    print(f"{args.output}: {args.output.stat().st_size} bytes, "
          f"page={page}, QCDT v3/{len(entries)} entries; "
          f"kernel=0x{fields[1]:08x}, ramdisk=0x{fields[3]:08x}, "
          f"tags=0x{fields[6]:08x}")


if __name__ == "__main__":
    main()
