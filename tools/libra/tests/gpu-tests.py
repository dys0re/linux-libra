#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the OEM GPU memory geometry, microcode and executed BFB writes."""
from pathlib import Path
import re
import subprocess
import tempfile

W = Path(__file__).resolve().parents[4]
source = (W / 'linux/drivers/iommu/arm/arm-smmu/qcom_iommu.c').read_text()
start = source.index('static void qcom_iommu_msm8992_bfb(')
fn = source[start:source.index('\n}\n', start) + 3]
oem = (W / 'kernel_xiaomi_msm8992/arch/arm/boot/dts/qcom/msm8992-iommu.dtsi').read_text()
oem = oem[oem.index('&kgsl_iommu {'):oem.index('&vfe_iommu {')]


def array(name):
    body = re.search(name + r'\s*=\s*<(.*?)>;', oem, re.S)[1]
    return [int(n, 0) for n in re.findall(r'0x[0-9a-f]+|\b[0-9]+\b', body)]


regs, values = array('qcom,iommu-bfb-regs'), array('qcom,iommu-bfb-data')
assert len(regs) == len(values) == 27
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef uint16_t u16;
typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a) / sizeof(a[0]))
struct qcom_iommu_dev { void *local_base; };
static uint32_t writes[0x3000 / 4], offsets[27];
static unsigned n;
static void writel_relaxed(uint32_t val, void *addr) {
    uintptr_t off = (uintptr_t)addr;
    assert(off < 0x3000 && !(off & 3) && n < 27);
    offsets[n++] = off;
    writes[off / 4] = val;
}
#define wmb() do {} while (0)
'''
main = '\nint main(void) { struct qcom_iommu_dev d = {0}; qcom_iommu_msm8992_bfb(&d); assert(n == 27);\n'
for i, (reg, value) in enumerate(zip(regs, values)):
    main += f'assert(offsets[{i}] == {reg}); assert(writes[{reg}/4] == {value});\n'
main += 'return 0; }\n'
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp) / 'bfb.c', Path(tmp) / 'bfb'
    c.write_text(prefix + fn + main)
    subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS actual GPU IOMMU BFB callback: all 27 aligned writes match OEM routing/micro-TLB settings')

ocmem = (W / 'linux/drivers/soc/qcom/ocmem.c').read_text()
assert '(0x0000003c + 0x4*(i0))' in ocmem
geometry = re.search(r'ocmem_8992_config = \{(.*?)\};', ocmem, re.S)[1]
assert '.num_regions = 4' in geometry and '.macro_size = SZ_128K' in geometry
catalog = (W / 'linux/drivers/gpu/drm/msm/adreno/a4xx_catalog.c').read_text()
chip = catalog[catalog.index('ADRENO_CHIP_IDS(0x04010800)'):]
chip = chip[:chip.index('\n\t},')]
assert '.revn = 418' in chip and '.gmem = SZ_512K' in chip
for name in ('a420_pm4.fw', 'a420_pfp.fw'):
    assert name in chip
print('PASS OEM A418 identity/GMEM and four-region OCMEM geometry/register stride')

dtb = W / 'build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb'


def prop(node, name, fmt='x'):
    return subprocess.check_output(['fdtget', '-t' + fmt, str(dtb), node, name], text=True).strip()


assert prop('/soc/gpu@fdb00000', 'compatible', 's') == 'qcom,adreno-418.0 qcom,adreno'
assert prop('/soc/iommu@fdb10000', 'qcom,iommu-secure-id') == '12'
assert prop('/soc/iommu@fdb10000/iommu-ctx@8000', 'qcom,ctx-asid') == '0'
assert prop('/soc/iommu@fdb10000/iommu-ctx@8000', 'interrupts') == '0 f1 4'
assert prop('/soc/sram@fdd00000', 'ranges') == '0 fec00000 100000'
for hz in (180000000, 300000000):
    assert prop(f'/soc/gpu@fdb00000/opp-table/opp-{hz}', 'opp-hz') == f'0 {hz:x}'
boot = (W / 'build/boot-libra-alpine-drm.img').read_bytes()
args = boot[64:576].split(b'\0')[0].decode().split()
assert 'msm.gpu=0' in args and 'qcom_iommu.msm8992_probe=0' in args
assert 'msm8992_probe' in ocmem and 'held for manual activation' in ocmem
assert 'held for manual activation' in source
assert not any('allow_vram_carveout=1' in a for a in args)
print('PASS GPU DT: OEM context/IRQ/OCMEM, 180-300MHz, manual activation gates and IOMMU protection retained')

for name in ('extract-libra-gpu-firmware.py', 'install-libra-gpu.sh', 'build-debian-rootfs.sh', 'build-debian-boot.sh', 'build-libra-mesa.py'):
    assert (W / 'scripts' / name).read_bytes() == (W / 'linux/tools/libra/scripts' / name).read_bytes()
print('PASS GPU build/installation script mirrors')

generated = W / 'build/libra-mesa/src/freedreno/common/freedreno_devices.h'
assert '{ {418, 0x40108ff}, "FD418"' in generated.read_text()
probe = (W / 'linux/tools/libra/tests/gpu-render.c').read_text()
assert '!strstr(renderer, "FD418")' in probe
assert 'glDrawArrays(GL_TRIANGLES' in probe and probe.count('glReadPixels(') == 2
assert 'btop fastfetch' in (W / 'scripts/configure-debian-rootfs.sh').read_text()
print('PASS Mesa A418 device info generated; shader/readback probe rejects silent fallback; requested utilities included')
