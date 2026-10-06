#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute manual CCI selection and verify failed PLL requests recover boot rate."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
src = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
helpers = src[src.index('static unsigned int msm8992_cci_voltage('):src.index('static int msm8992_set_voltage(')]
body = src[src.index('static int msm8992_cci_test_set('):src.index('DEFINE_DEBUGFS_ATTRIBUTE(msm8992_cci_test_fops')]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint64_t u64;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
static void info(const char*fmt,...){(void)fmt;}
#define dev_info(dev,...) info(__VA_ARGS__)
struct clk {unsigned long hz;};struct regulator {int uv;};
struct msm8992_cpr_plan {unsigned uv[10];};
struct msm8992_cpufreq {struct clk*cpu[2],*cci;struct regulator*apc[2];struct msm8992_cpr_plan plan[2];int lock,dev;};
struct scoped_mutex {int*p;};
static struct scoped_mutex lock_guard(int*p){assert(!*p);*p=1;return (struct scoped_mutex){p};}
static void unlock(struct scoped_mutex*g){assert(*g->p==1);*g->p=0;}
#define guard(t) struct scoped_mutex scoped __attribute__((cleanup(unlock))) = lock_guard
static unsigned calls;static int fail_set,no_effect,fail_restore;
static unsigned long clk_get_rate(struct clk*c){return c->hz;}
static int regulator_get_voltage(struct regulator*r){return r->uv;}
static int clk_set_rate(struct clk*c,unsigned long hz){assert(hz==300000000||hz==384000000);calls++;if(hz==384000000&&fail_set){c->hz=150000000;return -ETIMEDOUT;}if(hz==300000000&&fail_restore)return -EPERM;if(!no_effect)c->hz=hz;return 0;}
'''
main = r'''
int main(void){struct clk a={600000000},b={600000000},c={300000000};struct regulator ra={1000000};struct msm8992_cpufreq d={.cpu={&a,&b},.cci=&c,.apc={&ra},.plan={{{800000,800000,855000,855000,875000,905000,935000,970000,1080000,1150000}}}};
 assert(!msm8992_cci_test_set(&d,384000000)&&c.hz==384000000&&calls==1);
 assert(!msm8992_cci_test_set(&d,300000000)&&c.hz==300000000&&calls==2);
 calls=0;assert(msm8992_cci_test_set(&d,556800000)==-ERANGE&&!calls);
 a.hz=672000000;assert(msm8992_cci_test_set(&d,384000000)==-EBUSY&&!calls);a.hz=600000000;
 ra.uv=1005000;assert(msm8992_cci_test_set(&d,384000000)==-EBUSY&&!calls);ra.uv=1000000;
 d.plan[0].uv[5]=1010000;assert(msm8992_cci_test_set(&d,384000000)==-ERANGE&&!calls);d.plan[0].uv[5]=905000;
 fail_set=1;assert(msm8992_cci_test_set(&d,384000000)==-ETIMEDOUT&&c.hz==300000000&&calls==2);
 calls=0;fail_restore=1;assert(msm8992_cci_test_set(&d,384000000)==-ETIMEDOUT&&c.hz==150000000&&calls==2);
 fail_set=fail_restore=0;assert(!msm8992_cci_test_set(&d,300000000)&&c.hz==300000000);
 no_effect=1;assert(msm8992_cci_test_set(&d,384000000)==-EIO&&c.hz==300000000);
 assert(!d.lock&&ra.uv==1000000&&a.hz==600000000&&b.hz==600000000);
 puts("PASS actual CCI test: only 300/384MHz, CPU/voltage/calibration guards, correct readback, failed PLL recovered to boot auxiliary300MHz, recovery errors visible; no CPU/voltage changes");}
'''
target = workspace / 'build/validation/cci-bringup.c'
target.write_text(prefix + helpers + body + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
