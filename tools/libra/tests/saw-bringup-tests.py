#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the manual voltage pulse with fixed boot clocks and injected failures."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
src = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
body = src[src.index('static int msm8992_saw_test_set('):src.index('DEFINE_DEBUGFS_ATTRIBUTE(msm8992_saw_test_fops')]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint64_t u64;
#define dev_info(...) ((void)0)
struct clk {unsigned long hz;};struct regulator {int uv;};
struct msm8992_cpufreq {struct clk*cpu[2],*cci;struct regulator*apc[2];int lock,dev;};
static unsigned calls,reads;static int fail_set,fail_read;static int requested[8];
static void mutex_lock(int*m){assert(!*m);*m=1;}
static void mutex_unlock(int*m){assert(*m==1);*m=0;}
static unsigned long clk_get_rate(struct clk*c){return c->hz;}
static int regulator_get_voltage(struct regulator*r){reads++;return (int)reads==fail_read?-EIO:r->uv;}
static int regulator_set_voltage(struct regulator*r,int min,int max){assert(min==max&&(min==1000000||min==1005000));requested[calls++]=min;if((int)calls==fail_set)return -EIO;r->uv=min;return 0;}
static void usleep_range(unsigned lo,unsigned hi){assert(lo==1000&&hi==2000);}
'''
main = r'''
int main(void){struct clk a={600000000},b={600000000},c={300000000};struct regulator ra={1000000},rb={1000000};struct msm8992_cpufreq d={.cpu={&a,&b},.cci=&c,.apc={&ra,&rb}};
 for(unsigned cluster=0;cluster<2;cluster++){calls=reads=0;assert(!msm8992_saw_test_set(&d,cluster));assert(calls==2&&requested[0]==1005000&&requested[1]==1000000&&ra.uv==1000000&&rb.uv==1000000&&!d.lock);}
 calls=reads=0;assert(msm8992_saw_test_set(&d,2)==-EINVAL&&calls==0);
 a.hz=384000000;assert(msm8992_saw_test_set(&d,0)==-EBUSY&&calls==0);a.hz=600000000;
 c.hz=384000000;assert(msm8992_saw_test_set(&d,0)==-EBUSY&&calls==0);c.hz=300000000;
 ra.uv=1005000;assert(msm8992_saw_test_set(&d,0)==-EBUSY&&calls==0);ra.uv=1000000;
 for(int stage=1;stage<=2;stage++){calls=reads=0;fail_set=stage;assert(msm8992_saw_test_set(&d,0)==-EIO&&calls==(unsigned)stage&&!d.lock);assert(ra.uv==(stage==1?1000000:1005000));ra.uv=1000000;}
 fail_set=0;calls=reads=0;fail_read=2;assert(msm8992_saw_test_set(&d,0)==-EIO&&calls==1&&ra.uv==1005000&&!d.lock);
 assert(a.hz==600000000&&b.hz==600000000&&c.hz==300000000);
 puts("PASS actual manual SAW pulse: only 1.000->1.005->1.000 V, per-cluster boot-clock guard, PMIC readback, errors stop, failed restore retains higher voltage; no clock changes");}
'''
target = workspace / 'build/validation/saw-bringup.c'
target.write_text(prefix + body + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
