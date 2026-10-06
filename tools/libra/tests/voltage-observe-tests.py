#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute read-only voltage report and ensure boot frequency stays listed."""
from pathlib import Path
import subprocess

workspace=Path(__file__).resolve().parents[4]
src=(workspace/'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
report=src[src.index('static int msm8992_voltage_report_show('):src.index('DEFINE_SHOW_ATTRIBUTE(msm8992_voltage_report)')]
prefix=r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <errno.h>
typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
static void seq_printf(void*s,const char*format,...){(void)s;(void)format;}
struct seq_file {void*private;};
struct clk {unsigned long hz;};struct regulator {int uv;};struct regmap {u32 data[1024];};
struct plan {unsigned speedbin,revision,count;int backup;unsigned long hz[15];unsigned uv[15];};
struct msm8992_cpufreq {struct clk*cpu[2],*cci;struct regulator*apc[2];struct regmap*saw[2];struct plan plan[2];};
static unsigned reads;static int fail_read;
static unsigned long clk_get_rate(struct clk*c){return c->hz;}
static int regulator_get_voltage(struct regulator*r){return r->uv;}
static int regmap_read(struct regmap*m,unsigned off,u32*v){reads++;if((int)reads==fail_read)return -EIO;*v=m->data[off/4];return 0;}
'''
main=r'''
int main(void){
 struct clk a={600000000},b={600000000},c={300000000};struct regulator ra={1000000},rb={1000000};struct regmap ma={0},mb={0};
 struct msm8992_cpufreq d={.cpu={&a,&b},.cci=&c,.apc={&ra,&rb},.saw={&ma,&mb}};struct seq_file seq={&d};
 assert(!msm8992_voltage_report_show(&seq,0)&&reads==28);
 ra.uv=-EIO;reads=0;assert(msm8992_voltage_report_show(&seq,0)==-EIO&&reads==0);ra.uv=1000000;
 fail_read=4;reads=0;assert(msm8992_voltage_report_show(&seq,0)==-EIO&&reads==4);
 assert(a.hz==600000000&&b.hz==600000000&&c.hz==300000000&&ra.uv==1000000&&rb.uv==1000000);
 puts("PASS real voltage-report function: only clock/setpoint/SAW reads, errors propagated without changing any voltage or frequency");
}
'''
p=workspace/'build/validation/voltage-observe-report.c';p.write_text(prefix+report+main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)
# Observation probe returns before supply votes, CPR writes and policy registration.
start=src.index('\tif (observe) {',src.index('d->cci = devm_clk_get'))
end=src.index('\n\tret = dev_pm_genpd_set_performance_state',start)
branch=src[start:end]
assert 'return 0;' in branch and 'debugfs_create_file' in branch
for forbidden in ('regulator_set_voltage','clk_set_rate','writel','cpufreq_register_driver','dev_pm_genpd_set_performance_state'):
 assert forbidden not in branch
assert 'if (!observe)' in src[src.index('static int msm8992_cpufreq_probe'):start]
# The known 600MHz boot source must not force a transition/BUG_ON at registration.
a=src.index('\t\tfor (i = 0, n = 0; i < d->plan[c].count; i++)')
b=src.index('\n\t\tfor (i = 0; i < d->plan[c].count; i++)',a)
body=src[a:b]
code=r'''
#include <assert.h>
#include <stdio.h>
#define CPUFREQ_TABLE_END 0xffffffff
struct freq {unsigned frequency;};struct plan {unsigned count;unsigned long hz[15];};
struct data {struct plan plan[2];struct freq table[2][16];};
int main(void){struct data state={0},*d=&state;unsigned c=1,i,n;
unsigned long rates[]={300000000,300000000,384000000,480000000,633600000,768000000,864000000,960000000,1248000000,1344000000,1440000000,1536000000,1632000000,1689600000,1824000000};
state.plan[1].count=15;for(i=0;i<15;i++)state.plan[1].hz[i]=rates[i];
'''+body+r'''
assert(n==14&&state.table[1][2].frequency==600000&&state.table[1][3].frequency==633600&&state.table[1][13].frequency==1824000&&state.table[1][14].frequency==CPUFREQ_TABLE_END);
puts("PASS real A57 table builder includes 600MHz auxiliary point before 633.6MHz, avoiding unlisted-boot forced transition");}
'''
p=workspace/'build/validation/cpu-boot-point.c';p.write_text(code)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)
variant=workspace/'build/libra-voltage-observe.dtb'
for node in ('/soc/clock-controller@f9015000','/cpufreq@f9019000'):
 assert subprocess.check_output(['fdtget','-ts',str(variant),node,'status'],text=True).strip()=='okay'
 props=subprocess.check_output(['fdtget','-p',str(variant),node],text=True).splitlines()
 assert 'power-domains' not in props
print('PASS voltage observation DT omits implicit power-domain attachment for both manual probes')
