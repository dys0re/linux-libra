#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check real calibration code against the selected OEM tables and voltage math."""
from pathlib import Path
import random
import re
import subprocess

workspace = Path(__file__).resolve().parents[4]
build = workspace / "build/validation"
build.mkdir(parents=True, exist_ok=True)
header = (workspace / "linux/drivers/cpufreq/qcom-msm8992-cpr.h").read_text()
fields = dict(fuse_init="qcom,cpr-fuse-init-voltage", backup_init="qcom,cpr-fuse-redun-init-voltage", remap="qcom,fuse-remap-source", ref="qcom,cpr-init-voltage-ref", adjust="qcom,cpr-init-voltage-adjustment", version_map="qcom,cpr-fuse-version-map", fuse_floor="qcom,cpr-voltage-floor", fuse_ceiling="qcom,cpr-voltage-ceiling", floor="qcom,cpr-voltage-floor-override", ceiling="qcom,cpr-voltage-ceiling-override", map="qcom,cpr-corner-map", freq_map="qcom,cpr-corner-frequency-map", max_corners="qcom,cpr-speed-bin-max-corners", scaling="qcom,cpr-voltage-scaling-factor-max", ro="qcom,cpr-fuse-ro-sel", backup_ro="qcom,cpr-fuse-redun-ro-sel")
plans = []
for c in range(2):
    node = f"/soc/regulator@{0xf9019000+c*0x1000:x}"
    plan = {}
    for name, prop in fields.items():
        raw = subprocess.check_output(["fdtget", "-tx", str(workspace / "build/factory-libra-reference.dtb"), node, prop], text=True)
        values = [int(x, 16) for x in raw.split()]
        if name == "adjust": values = [x if x < 2**31 else x - 2**32 for x in values]
        plan[name] = values
        declared = re.search(r"cpr" + str(c) + "_" + name + r"\[\] = \{(.*?)\};", header, re.S).group(1)
        assert [int(x, 0) for x in declared.replace("\n", "").split(",") if x.strip()] == values, prop
    plans.append(plan)

prefix = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
typedef uint32_t u32;typedef uint64_t u64;typedef unsigned char u8;
#define U32_MAX UINT32_MAX
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define min(a,b) ((a)<(b)?(a):(b))
#define max(a,b) ((a)>(b)?(a):(b))
#define clamp(v,l,h) min(max(v,l),h)
#define div_u64(a,b) ((a)/(b))
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
"""
main = r"""
int main(int argc,char**argv){
 u8 data[0x500];struct msm8992_cpr_plan plan={0};
 if(argc!=3||fread(data,1,sizeof data,stdin)!=sizeof data)return 2;
 int ret=msm8992_cpr_calculate(data,atoi(argv[1]),atoi(argv[2]),&plan);
 printf("%d %u %u %u\n",ret,plan.count,plan.revision,plan.backup);
 for(unsigned i=0;i<plan.count;i++)printf("%lu %u\n",plan.hz[i],plan.uv[i]);
}
"""
source = build / "cpu-cpr-model.c"
source.write_text(prefix + header + main)
subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-const-variable", str(source), "-o", str(source.with_suffix(""))], check=True)

def bits(data, row, offset, width):
    val = int.from_bytes(data, "little")
    return (val >> (row * 64 + offset)) & ((1 << width) - 1)

def reference(data, c, speedbin):
    p = plans[c]
    backup = bits(data, 62, 48, 3) == 1
    revision = bits(data, 137, 34, 3)
    remapped = 0
    pos = 0
    for row, offset, width, method in zip(*[iter(p["remap"])] * 4):
        assert method == 0
        remapped |= bits(data, row, offset, width) << pos
        pos += width
    ro = [(remapped >> off) & 7 for off in p["backup_ro"]] if backup else [bits(data, 140 if c else 138, off, 3) for off in p["ro"]]
    match = None
    for i, t in enumerate(zip(*[iter(p["version_map"])] * 7)):
        if t[0] not in (speedbin, 0xffffffff) or t[1] not in (0, 0xffffffff) or t[2] != revision: continue
        if all(a == b or a == 0xffffffff for a, b in zip(t[3:], ro)): match = i; break
    values = []
    for i, (row, offset, width, method) in enumerate(zip(*[iter(p["backup_init" if backup else "fuse_init"])] * 4)):
        value = (remapped >> offset) & 63 if backup else bits(data, row, offset, width)
        uv = p["ref"][i] + (-1 if value & 32 else 1) * (value & 31) * 10000
        if match is not None: uv += p["adjust"][match * 4 + i]
        values.append(max(p["fuse_floor"][i], min(p["fuse_ceiling"][i], uv)))
    endpoints = p["max_corners"][2:6] if c else p["max_corners"][speedbin * 6 + 2:speedbin * 6 + 6]
    frequencies = p["freq_map"][1::2]
    result = []
    for i, hz in enumerate(frequencies[:endpoints[-1]]):
        fc = p["map"][i] - 1
        uv = values[fc]
        if fc and endpoints[fc - 1] < i + 1 < endpoints[fc]:
            hi, lo = frequencies[endpoints[fc] - 1], frequencies[endpoints[fc - 1] - 1]
            if hi > lo and values[fc] > values[fc - 1]:
                delta = min((hi - hz) * (values[fc] - values[fc - 1]) // (hi - lo), (hi - hz) * p["scaling"][fc] // 1000000)
                uv = ((values[fc] - delta + 4999) // 5000) * 5000
        uv = max(p["floor"][i + 2], min(p["ceiling"][i + 2], uv))
        result.append((hz, uv))
    return revision, backup, result

rng = random.Random(8992)
cases = [bytes(0x500)] + [rng.randbytes(0x500) for _ in range(60)]
def set_bits(data, row, offset, width, value):
    integer = int.from_bytes(data, "little")
    shift = row * 64 + offset
    integer = (integer & ~(((1 << width) - 1) << shift)) | (value << shift)
    return integer.to_bytes(len(data), "little")
for cluster in (0, 1):
    for revision in range(5):
        for backup in (False, True):
            data = set_bits(bytes(0x500), 137, 34, 3, revision)
            if backup: data = set_bits(data, 62, 48, 3, 1)
            if cluster:
                ro = 4 if revision < 3 else 2
                if backup:
                    data = set_bits(data, 136, 19, 3, ro)
                else:
                    for off in plans[1]["ro"]: data = set_bits(data, 140, off, 3, ro)
            cases.append(data)
for c in (0, 1):
    for speedbin in ((0, 1) if c == 0 else (0,)):
        for data in cases:
            revision, backup, expected = reference(data, c, speedbin)
            raw = subprocess.check_output([str(source.with_suffix("")), str(c), str(speedbin)], input=data).decode().splitlines()
            result, count, got_rev, got_backup = map(int, raw[0].split())
            assert result == 0 and count == len(expected) and got_rev == revision and got_backup == backup
            assert [tuple(map(int, row.split())) for row in raw[1:]] == expected
        assert expected[-1][0] == (1824000000 if c else (1440000000 if speedbin else 1248000000))
# Known unprogrammed-fuse factory default, including interpolation and clipping.
assert [uv for hz, uv in reference(bytes(0x500), 0, 0)[2]] == [800000,800000,900000,900000,940000,1000000,1030000,1070000,1180000]
assert [uv for hz, uv in reference(bytes(0x500), 1, 0)[2]] == [900000,900000,900000,900000,900000,945000,975000,1000000,1060000,1080000,1100000,1115000,1115000,1115000,1180000]
print("PASS exact OEM CPR tables; primary/redundant packing, revision/RO tuple matching, 5mV capped interpolation and voltage limits across primary/backup, all revision matches and 243 cases; A53 bin-dependent maximum and A57 1.824GHz")

# Execute the real transaction functions against fake supplies/clocks.
driver = (workspace / "linux/drivers/cpufreq/qcom-msm8992-cpufreq.c").read_text()
assert re.search(r'static int voltage_offset_uv = -50000;', driver)
assert 'module_param(voltage_offset_uv, int, 0400);' in driver
body = driver[driver.index("struct msm8992_cpufreq {"):driver.index("static int msm8992_voltage_report_show")] + driver[driver.index("static struct msm8992_cpufreq *msm8992_dvfs"):driver.index("static int msm8992_policy_init")]
stubs = r"""
#include <assert.h>
struct device {int unused;};
struct clk {unsigned long hz;int id;};
struct regulator {unsigned uv;int id;};
struct mutex {int unused;};
struct cpufreq_frequency_table {unsigned frequency;};
struct cpufreq_policy {unsigned cpu;void *driver_data;struct cpufreq_frequency_table *freq_table;};
#define guard(x) (void)
#define dev_warn_ratelimited(...) ((void)0)
#define dev_warn(...) ((void)0)
#define dev_err(...) ((void)0)
static unsigned warnings;
static unsigned long clk_get_rate(struct clk *c);
static int clk_set_rate(struct clk *c,unsigned long hz);
static int regulator_get_voltage(struct regulator *r);
static int regulator_set_voltage(struct regulator *r,unsigned lo,unsigned hi);
"""
main = r"""
static struct clk clocks[3]={{600000000,0},{600000000,1},{300000000,2}};
static struct regulator rails[2]={{1180000,0},{1180000,1}};
static struct msm8992_cpufreq state;
static int fail_cpu,fail_cci;
static unsigned long clk_get_rate(struct clk*c){return c->hz;}
static int regulator_get_voltage(struct regulator*r){return r->uv;}
static unsigned required(unsigned uv){return (int)uv+state.voltage_offset_uv;}
static void check_volts(void){
 for(unsigned c=0;c<2;c++)assert(rails[c].uv>=required(msm8992_voltage(&state.plan[c],clocks[c].hz)));
 assert(rails[0].uv>=required(msm8992_cci_voltage(&state.plan[0],clocks[2].hz)));
}
static int clk_set_rate(struct clk*c,unsigned long hz){
 if(c->id==2){if(fail_cci==1)return -EIO;if((fail_cci==2&&hz!=300000000&&hz!=600000000)||(fail_cci==3&&hz==134400000)){c->hz=150000000;return -EIO;}assert(rails[0].uv>=required(msm8992_cci_voltage(&state.plan[0],hz)));}
 else{assert(rails[c->id].uv>=required(msm8992_voltage(&state.plan[c->id],hz)));assert(rails[c->id].uv>=required(msm8992_voltage(&state.plan[c->id],600000000)));if(fail_cpu){c->hz=600000000;return -ETIMEDOUT;}}
 c->hz=hz;check_volts();return 0;
}
static int regulator_set_voltage(struct regulator*r,unsigned lo,unsigned hi){assert(lo==hi);r->uv=lo;check_volts();return 0;}
static void run(int offset){
 u8 fuses[0x500]={0};
 memset(&state,0,sizeof(state));state.voltage_offset_uv=offset;
 clocks[0].hz=clocks[1].hz=600000000;clocks[2].hz=300000000;
 rails[0].uv=rails[1].uv=1180000;fail_cpu=fail_cci=0;
 assert(!msm8992_cpr_calculate(fuses,0,1,&state.plan[0]));assert(!msm8992_cpr_calculate(fuses,1,0,&state.plan[1]));
 for(unsigned c=0;c<2;c++){state.cpu[c]=&clocks[c];state.apc[c]=&rails[c];}
 state.cci=&clocks[2];
 struct cpufreq_frequency_table a53[]={{384000},{1440000}},a57[]={{384000},{1824000}};
 struct cpufreq_policy p0={.cpu=0,.driver_data=&state,.freq_table=a53},p4={.cpu=4,.driver_data=&state,.freq_table=a57};
 assert(!msm8992_target(&p0,1));assert(clocks[0].hz==1440000000&&clocks[2].hz==787200000);
 assert(!msm8992_target(&p4,1));assert(clocks[1].hz==1824000000);
 assert(!msm8992_target(&p0,0));assert(clocks[0].hz==384000000&&clocks[2].hz==787200000);
 assert(rails[0].uv==required(msm8992_cci_voltage(&state.plan[0],787200000)));
 assert(!msm8992_target(&p4,0));assert(clocks[2].hz==134400000);
 assert(rails[0].uv==required(msm8992_voltage(&state.plan[0],600000000)));
 fail_cci=1;assert(msm8992_target(&p0,1)==-EIO);assert(clocks[0].hz==384000000);check_volts();
 fail_cci=0;fail_cpu=1;assert(msm8992_target(&p0,1)==-ETIMEDOUT);assert(clocks[0].hz==600000000);check_volts();
 fail_cpu=0;assert(!msm8992_target(&p0,0));assert(!msm8992_target(&p4,1));check_volts();
 fail_cci=2;assert(msm8992_target(&p4,0)==-EIO);assert(clocks[0].hz==600000000&&clocks[1].hz==600000000&&clocks[2].hz==300000000);check_volts();
 fail_cci=0;assert(!msm8992_target(&p0,1));assert(!msm8992_target(&p4,1));assert(!msm8992_target(&p0,0));
 fail_cci=3;assert(msm8992_target(&p4,0)==-EIO);assert(clocks[0].hz==384000000&&clocks[1].hz==1824000000&&clocks[2].hz==787200000);check_volts();
 fail_cci=0;
 struct msm8992_cpr_plan original[2]={state.plan[0],state.plan[1]};
 struct cpufreq_frequency_table full[2][MSM8992_MAX_CORNERS+1];unsigned count[2]={0};
 for(unsigned c=0;c<2;c++)for(unsigned i=0;i<state.plan[c].count;i++){
  if(c&&state.plan[c].hz[i]==633600000)full[c][count[c]++].frequency=600000;
  if(state.plan[c].hz[i]>=384000000)full[c][count[c]++].frequency=state.plan[c].hz[i]/1000;
 }
 p0.freq_table=full[0];p4.freq_table=full[1];
 /* Every pair exercises the shared CCI vote and both auxiliary voltage floors. */
 for(unsigned a=0;a<count[0];a++)for(unsigned b=0;b<count[1];b++){
  assert(!msm8992_target(&p0,a));assert(!msm8992_target(&p4,b));
  assert(clocks[0].hz==full[0][a].frequency*1000UL&&clocks[1].hz==full[1][b].frequency*1000UL);
  for(unsigned c=0;c<2;c++){
   unsigned expected=max(msm8992_voltage(&state.plan[c],clocks[c].hz),msm8992_voltage(&state.plan[c],600000000));
   if(!c)expected=max(expected,msm8992_cci_voltage(&state.plan[0],clocks[2].hz));
   assert(rails[c].uv==required(expected));
  }
 }
 assert(!memcmp(original,state.plan,sizeof(original)));
}
int main(void){
 run(0);run(-50000);
 (void)warnings;
 puts("PASS real DVFS transaction at factory and -50mV: every CPU OPP pair, unchanged calibration, offset once after shared CCI/auxiliary votes, voltage/clock ordering and failure recovery");
}
"""
source = build / "cpu-cpr-transaction.c"
source.write_text(prefix + '#include <string.h>\n' + header + stubs + body + main)
subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable", str(source), "-o", str(source.with_suffix(""))], check=True)
subprocess.run([str(source.with_suffix(""))], check=True)
