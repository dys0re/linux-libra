#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract only radio firmware from the supplied OEM FAT16 flashing images.

Wi-Fi payloads are unchanged; add the ath10k API5 IE container (WMI/HTT TLV).
Bluetooth files are unchanged, renamed for the kernel Rome firmware loader.
No downloads, mounts, writes to stock images, or device calibration overrides.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Fat16:
    def __init__(self, image):
        self.data = image.read_bytes()
        b = self.data
        self.bps = struct.unpack_from('<H', b, 11)[0]
        self.spc = b[13]
        reserved, = struct.unpack_from('<H', b, 14)
        nfats = b[16]
        self.entries, = struct.unpack_from('<H', b, 17)
        spf, = struct.unpack_from('<H', b, 22)
        if b[510:512] != b'\x55\xaa' or b[54:62] != b'FAT16   ':
            raise ValueError(f'{image}: expected factory FAT16 volume')
        self.fat = reserved * self.bps
        self.root = (reserved + nfats * spf) * self.bps
        self.start = self.root + ((self.entries * 32 + self.bps - 1) // self.bps) * self.bps
        self.cluster_size = self.spc * self.bps

    def chain(self, cluster):
        out = bytearray()
        seen = set()
        while 2 <= cluster < 0xfff8:
            if cluster in seen or cluster >= 0xfff0:
                raise ValueError('invalid/cyclic FAT chain')
            seen.add(cluster)
            off = self.start + (cluster - 2) * self.cluster_size
            if off + self.cluster_size > len(self.data):
                raise ValueError('allocated cluster outside image')
            out += self.data[off:off + self.cluster_size]
            cluster, = struct.unpack_from('<H', self.data, self.fat + 2 * cluster)
        return bytes(out)

    def read(self, path):
        directory = self.data[self.root:self.root + self.entries * 32]
        parts = path.lower().split('/')
        for index, part in enumerate(parts):
            found = None
            for off in range(0, len(directory), 32):
                ent = directory[off:off + 32]
                if ent[0] == 0:
                    break
                if ent[0] == 0xe5 or ent[11] & 0x08:
                    continue
                name = ent[:8].decode('ascii').rstrip().lower()
                ext = ent[8:11].decode('ascii').rstrip().lower()
                if ext:
                    name += '.' + ext
                if name == part:
                    found = ent
                    break
            if found is None:
                raise FileNotFoundError(path)
            cluster, = struct.unpack_from('<H', found, 26)
            length, = struct.unpack_from('<I', found, 28)
            payload = self.chain(cluster)
            if index == len(parts) - 1:
                if found[11] & 0x10 or length > len(payload):
                    raise ValueError('invalid file entry')
                return payload[:length]
            if not found[11] & 0x10:
                raise NotADirectoryError(part)
            directory = payload


def ie(kind, value):
    return struct.pack('<II', kind, len(value)) + value + b'\0' * (-len(value) % 4)


def extract(images, output):
    wlan = Fat16(images / 'NON-HLOS.bin')
    bt = Fat16(images / 'BTFM.bin')
    sources = {}
    for name in ('qwlan30.bin', 'otp30.bin', 'bdwlan30.bin'):
        sources[name] = wlan.read('image/' + name)
    for name in ('btfw32.tlv', 'btnv32.bin'):
        sources[name] = bt.read('image/' + name)
    for name in ('qwlan30.bin', 'otp30.bin'):
        if sources[name][:4] != b'SGMT':
            raise ValueError(f'{name}: expected OEM BMI segmented image')
    if len(sources['bdwlan30.bin']) != 8124:
        raise ValueError('unexpected QCA6174 hw3 board data length')
    # Retain every byte of the factory patch and NVM TLV images.
    for name, typ in [('btfw32.tlv', 1), ('btnv32.bin', 2)]:
        header, = struct.unpack_from('<I', sources[name])
        if header & 255 != typ or header >> 8 != len(sources[name]) - 4:
            raise ValueError(f'{name}: invalid factory TLV length/type')
    product, rom = struct.unpack_from('<HH', sources['btfw32.tlv'], 16)
    if (product, rom) != (8, 0x0302):
        raise ValueError(f'unsupported Rome patch product/ROM: {product:#x}/{rom:#x}')
    # qcacld ol_download_firmware executes OTP param0 after board loading but
    # does not reject its return code. Use ath10k's firmware-scoped flag for
    # that policy; OTP is still downloaded/executed, and its bytes are intact.
    version = b'Xiaomi-libra-OEM-6.1.7'
    magic = b'QCA-ATH10K\0'
    fw = magic + b'\0' * (-len(magic) % 4) + ie(0, version) + ie(2, bytes([1 << 7]))
    fw += ie(3, sources['qwlan30.bin']) + ie(4, sources['otp30.bin'])
    fw += ie(5, struct.pack('<I', 4)) + ie(6, struct.pack('<I', 3))
    files = {
        'ath10k/QCA6174/hw3.0/firmware-5.bin': fw,
        'ath10k/QCA6174/hw3.0/board.bin': sources['bdwlan30.bin'],
        'qca/rampatch_00440302.bin': sources['btfw32.tlv'],
        'qca/btnv32.bin': sources['btnv32.bin'],
        'qca/nvm_00440302.bin': sources['btnv32.bin'],
    }
    for name, data in files.items():
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    manifest = {
        'source': str(images),
        'images': {name: sha((images / name).read_bytes()) for name in ('NON-HLOS.bin', 'BTFM.bin')},
        'inputs': {name: {'size': len(data), 'sha256': sha(data)} for name, data in sources.items()},
        'outputs': {name: {'size': len(data), 'sha256': sha(data)} for name, data in files.items()},
        'wifi_container': {'api': 5, 'wmi_op_version': 4, 'htt_op_version': 3,
                           'features': ['ignore-otp-result'],
                           'otp_policy': 'Execute OTP; follow OEM loader return-code policy.'},
        'notes': ['WLAN/OTP payloads unchanged; only ath10k IE wrapper added.',
                  'Default OEM x11 board bdwlan30.bin; not a10 board or generic firmware.',
                  'ROM/SOC selection and wireless operation still require device validation.',
                  'No MAC address or per-device calibration from factory persist copied.'],
    }
    (output / 'libra-oem-radio-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    workspace = Path(__file__).resolve().parents[1]
    parser.add_argument('--images', type=Path, default=workspace / 'libra_images_6.1.7_20151221.0000.11_5.1_cn/images')
    parser.add_argument('--output', type=Path, default=workspace / 'build/libra-radio-firmware')
    args = parser.parse_args()
    extract(args.images, args.output)
