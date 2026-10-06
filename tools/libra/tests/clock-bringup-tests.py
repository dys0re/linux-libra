#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute manual CPU frequency selection with fixed voltage and factory CCI limits."""
from pathlib import Path
import subprocess
import re

workspace = Path(__file__).resolve().parents[4]
src = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
header = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpr.h').read_text()
maps = '\n'.join(re.findall(r'static const u32 cci[01]_map\[\] = .*?;', header))
helpers = src[src.index('static unsigned int msm8992_voltage('):src.index('static unsigned int msm8992_cci_voltage(')]
body = src[src.index('struct msm8992_clock_test {'):src.index('DEFINE_DEBUGFS_ATTRIBUTE(msm8992_clock_test_fops')]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint64_t u64;typedef uint32_t u32;
#define max(a,b) ((a)>(b)?(a):(b))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
static void info(const char*format,...){(void)format;}
#define dev_info(dev,...) info(__VA_ARGS__)
struct clk {unsigned long hz;unsigned cluster;};struct regulator {int uv;};
struct msm8992_cpr_plan {unsigned count;unsigned long hz[4];unsigned uv[4];};
struct msm8992_cpufreq {struct clk*cpu[2],*cci;struct regulator*apc[2];struct msm8992_cpr_plan plan[2];int lock,dev;};
struct scoped_mutex {int*p;};
static struct scoped_mutex lock_guard(int*p){assert(!*p);*p=1;return (struct scoped_mutex){p};}
static void unlock(struct scoped_mutex*g){assert(*g->p==1);*g->p=0;}
#define guard(t) struct scoped_mutex scoped __attribute__((cleanup(unlock))) = lock_guard
static unsigned calls;static int fail_set,fail_round,no_effect;static unsigned long last;
static unsigned long clk_get_rate(struct clk*c){return c->hz;}
static int regulator_get_voltage(struct regulator*r){return r->uv;}
static long clk_round_rate(struct clk*c,unsigned long hz){if(fail_round)return -EIO;switch(hz){case 384000000:case 600000000:case 672000000:return hz;case 460800000:return c->cluster?480000000:hz;default:return 600000000;}}
static int clk_set_rate(struct clk*c,unsigned long hz){assert(hz<=672000000);calls++;last=hz;if(fail_set){c->hz=600000000;return -ETIMEDOUT;}if(!no_effect)c->hz=hz;return 0;}
'''
main = r'''
int main(void){struct clk a={600000000,0},b={600000000,1},c={300000000,2};struct regulator ra={1000000},rb={1000000};
 struct msm8992_cpufreq d={.cpu={&a,&b},.cci=&c,.apc={&ra,&rb},.plan={{4,{384000000,600000000,672000000,787200000},{800000,855000,875000,905000}},{4,{384000000,480000000,633600000,768000000},{900000,900000,900000,920000}}}};
 struct msm8992_clock_test ta={&d,0},tb={&d,1};
 assert(!msm8992_clock_test_set(&ta,384000000)&&a.hz==384000000&&last==384000000);
 assert(!msm8992_clock_test_set(&ta,600000000)&&a.hz==600000000);
 assert(!msm8992_clock_test_set(&ta,672000000)&&a.hz==672000000);
 assert(!msm8992_clock_test_set(&tb,384000000)&&b.hz==384000000);
 calls=0;assert(msm8992_clock_test_set(&ta,787200000)==-ERANGE&&!calls);
 assert(msm8992_clock_test_set(&tb,633600000)==-ERANGE&&!calls);
 assert(msm8992_clock_test_set(&ta,650000000)==-EINVAL&&!calls);
 b.hz=768000000;assert(msm8992_clock_test_set(&ta,672000000)==-ERANGE&&!calls);b.hz=600000000;
 c.hz=556800000;assert(msm8992_clock_test_set(&ta,672000000)==-EBUSY&&!calls);c.hz=300000000;
 ra.uv=1005000;assert(msm8992_clock_test_set(&ta,672000000)==-EBUSY&&!calls);ra.uv=1000000;
 d.plan[0].uv[2]=1010000;assert(msm8992_clock_test_set(&ta,672000000)==-ERANGE&&!calls);d.plan[0].uv[2]=875000;
 fail_round=1;assert(msm8992_clock_test_set(&ta,672000000)==-EIO&&!calls);fail_round=0;
 fail_set=1;assert(msm8992_clock_test_set(&ta,384000000)==-ETIMEDOUT&&a.hz==600000000);fail_set=0;
 no_effect=1;assert(msm8992_clock_test_set(&ta,384000000)==-EIO);
 assert(!d.lock&&ra.uv==1000000&&rb.uv==1000000&&c.hz==300000000);
 puts("PASS actual CPU clock test: persistent requested rate, calibrated voltage and factory CCI guards, unsupported rates rejected, PLL/readback errors propagated, no voltage or CCI changes");}
'''
target = workspace / 'build/validation/clock-bringup.c'
target.write_text(prefix + maps + helpers + body + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
