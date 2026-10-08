#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Copy Adreno microcode unchanged from the supplied OEM system image."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def extract(image, output):
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    with tempfile.TemporaryDirectory(prefix='libra-gpu-') as tmp:
        raw = Path(tmp) / 'system.ext4'
        subprocess.run(['simg2img', str(image), str(raw)], check=True)
        for name in ('a420_pm4.fw', 'a420_pfp.fw'):
            target = output / 'qcom' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['debugfs', '-R',
                            f'dump /etc/firmware/{name} {target}', str(raw)], check=True)
            data = target.read_bytes()
            if len(data) < 8 or len(data) % 4:
                raise ValueError(f'{name}: invalid 32-bit microcode size')
            files[f'qcom/{name}'] = {'size': len(data), 'sha256': digest(target),
                                     'source': f'/etc/firmware/{name}'}
    receipt = {'image': str(image), 'image_sha256': digest(image),
               'files': files, 'payload_modified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    workspace = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, default=workspace /
                        'libra_images_6.1.7_20151221.0000.11_5.1_cn/images/system.img')
    parser.add_argument('--output', type=Path, default=workspace / 'build/libra-gpu-firmware')
    args = parser.parse_args()
    extract(args.image.resolve(), args.output.resolve())
