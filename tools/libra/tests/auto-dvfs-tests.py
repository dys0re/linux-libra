#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check automatic DVFS delivery and execute thermal readiness prerequisites."""
from pathlib import Path
import subprocess
import struct

workspace = Path(__file__).resolve().parents[4]
src = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
start = src.index('static int msm8992_thermal_ready(')
body = src[start:src.index('\n}\n', start) + 3]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define EPROBE_DEFER 517
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define IS_ERR(p) ((intptr_t)(p)<0 && (intptr_t)(p)>-4096)
#define dev_err_probe(dev,err,...) (err)
struct device {int unused;};struct thermal_zone_device {int id;};
static const char*names[]={"tsens7-thermal","tsens9-thermal","tsens10-thermal","tsens13-thermal","tsens14-thermal"};
static struct thermal_zone_device zones[5];static unsigned queried,readings;static int missing=-1,invalid=-1;
static struct thermal_zone_device*thermal_zone_get_zone_by_name(const char*name){unsigned id=queried++;assert(id<5&&!strcmp(name,names[id]));zones[id].id=id;return (int)id==missing?(void*)(intptr_t)-ENODEV:&zones[id];}
static int thermal_zone_get_temp(struct thermal_zone_device*z,int*temp){readings++;if(z->id==invalid)return -EAGAIN;*temp=35000+z->id*1000;return 0;}
'''
main = r'''
int main(void){struct device d={0};assert(!msm8992_thermal_ready(&d)&&queried==5&&readings==5);
 for(int id=0;id<5;id++){queried=readings=0;missing=id;assert(msm8992_thermal_ready(&d)==-EPROBE_DEFER&&queried==(unsigned)id+1&&readings==(unsigned)id);}
 missing=-1;for(int id=0;id<5;id++){queried=readings=0;invalid=id;assert(msm8992_thermal_ready(&d)==-EPROBE_DEFER&&readings==(unsigned)id+1);}
 puts("PASS actual thermal prerequisite: all five CPU/shared thermal zones require valid readings; a missing or invalid zone defers DVFS activation");}
'''
target = workspace / 'build/validation/auto-dvfs-thermal.c'
target.write_text(prefix + body + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
boot = (workspace / 'build/boot-libra-alpine-drm.img').read_bytes()
args = boot[64:576].split(b'\0', 1)[0].decode().split()
for flag in ('qcom_tsens.msm8992_probe=1', 'clk_cpu_msm8992.clusters_probe=1', 'qcom_msm8992_cpufreq.enable=1'):
    assert flag in args
assert not any('observe=' in flag or '_test=' in flag for flag in args)
config = (workspace / 'build/libra/.config').read_text()
assert 'CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y' in config
assert 'CONFIG_CPU_FREQ_THERMAL=y' in config
clk = (workspace / 'linux/drivers/clk/qcom/clk-cpu-msm8992.c').read_text()
assert 'dev_pm_genpd_set_performance_state(dev, 4)' in clk
assert 'dev_pm_genpd_set_performance_state(dev, 6)' in src
native = workspace / 'build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb'
expected = native.read_bytes()
fields = struct.unpack_from('<10I', boot, 8)
page = fields[7]
align = lambda size: (size + page - 1) // page * page
dt_start = page + align(fields[0]) + align(fields[2])
offset = struct.unpack_from('<10I', boot, dt_start + 12)[8]
assert boot[dt_start + offset:dt_start + offset + len(expected)] == expected
for node in ('/soc/clock-controller@f9015000', '/cpufreq@f9019000'):
    props = subprocess.check_output(['fdtget', '-p', str(native), node], text=True).splitlines()
    if 'status' in props:
        assert subprocess.check_output(['fdtget', '-ts', str(native), node, 'status'], text=True).strip() == 'okay'
    assert 'power-domains' in props
print('PASS auto-DVFS boot: exact full DTB, automatic sensor/clock/policy gates, schedutil default and CPU cooling, encoded factory RPM votes, no debug test modes')
