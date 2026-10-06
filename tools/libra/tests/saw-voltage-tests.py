#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute per-cluster SAW voltage writes, acknowledgment, affinity and failures."""
from pathlib import Path
import subprocess

workspace=Path(__file__).resolve().parents[4]
src=(workspace/'linux/drivers/regulator/qcom_spmi-regulator.c').read_text()
body=src[src.index('#define SAW3_VCTL_DATA_MASK'):src.index('static const struct regulator_ops spmi_smps_ops')]
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;typedef uint8_t u8;
#define BIT(n) (1U << (n))
#define SAW3_ID 0x04
#define SAW3_VERSION 0xfd0
#define SAW3_AVS_CTL 0x20
#define SAW3_VCTL 0x1c
#define SAW3_SPM_PMIC_DATA_3 0x4c
#define SAW3_RST 0x18
#define SAW3_PMIC_STS 0x14
struct regmap {u32 words[1024];};
struct spmi_regulator {struct regmap*saw_regmap;unsigned saw_cpu;u32 saw_init_delay;bool saw_initialized;};
struct regulator_dev {struct spmi_regulator*vreg;};
static unsigned reads,writes,delays,last_cpu;static int fail_read,fail_write,fail_ipi,fail_range;static bool no_ack;
static unsigned offsets[256];
static struct spmi_regulator*rdev_get_drvdata(struct regulator_dev*d){return d->vreg;}
static int regmap_read(struct regmap*m,unsigned off,u32*v){reads++;if((int)reads==fail_read)return -EIO;*v=m->words[off/4];return 0;}
static int regmap_write(struct regmap*m,unsigned off,u32 v){offsets[writes++]=off;if((int)writes==fail_write)return -EIO;m->words[off/4]=v;if(off==SAW3_VCTL&&!no_ack)m->words[SAW3_PMIC_STS/4]=v&255;return 0;}
static void udelay(unsigned d){delays+=d;}
static int smp_call_function_single(unsigned cpu,void(*fn)(void*),void*p,bool wait){last_cpu=cpu;assert(wait);if(fail_ipi)return fail_ipi;fn(p);return 0;}
static int spmi_sw_selector_to_hw(struct spmi_regulator*v,unsigned sel,u8*r,u8*voltage){*r=fail_range?1:0;*voltage=sel;return 0;}
'''
main=r'''
static void setup(struct regmap*m){
 reads=writes=delays=0;fail_read=fail_write=fail_ipi=fail_range=0;no_ack=false;
 m->words[SAW3_VCTL/4]=0xabc30080;m->words[SAW3_SPM_PMIC_DATA_3/4]=0xfbc30080;
 m->words[SAW3_ID/4]=0x2010086f;m->words[SAW3_VERSION/4]=0x30000000;
 m->words[SAW3_AVS_CTL/4]=0;m->words[SAW3_PMIC_STS/4]=128;
}
int main(void){
 struct regmap a={0},b={0};struct spmi_regulator va={.saw_regmap=&a,.saw_cpu=0},vb={.saw_regmap=&b,.saw_cpu=4};struct regulator_dev ra={&va},rb={&vb};
 setup(&a);setup(&b);
 assert(!spmi_regulator_saw_set_voltage(&ra,184)&&last_cpu==0);
 assert(a.words[SAW3_VCTL/4]==((0xabc30080&~0x700ffU)|184));
 assert(a.words[SAW3_SPM_PMIC_DATA_3/4]==((0xfbc30080&~0x700ffU)|184));
 assert(offsets[0]==SAW3_RST&&offsets[1]==SAW3_VCTL&&offsets[2]==SAW3_SPM_PMIC_DATA_3);
 assert((b.words[SAW3_VCTL/4]&255)==128);
 assert(!spmi_regulator_saw_set_voltage(&rb,190)&&last_cpu==4);
 for(int failure=1;failure<=3;failure++){setup(&a);fail_read=failure;assert(spmi_regulator_saw_set_voltage(&ra,184)==-EIO&&writes==0);}
 setup(&a);fail_range=1;assert(spmi_regulator_saw_set_voltage(&ra,184)==-EINVAL&&writes==0);
 setup(&a);fail_ipi=-ENXIO;assert(spmi_regulator_saw_set_voltage(&ra,184)==-ENXIO&&writes==0);
 setup(&a);a.words[SAW3_AVS_CTL/4]=(1U<<27)|1;no_ack=true;
 assert(spmi_regulator_saw_set_voltage(&ra,184)==-ETIMEDOUT&&delays==50);
 assert(a.words[SAW3_AVS_CTL/4]==((1U<<27)|1));
 for(int failure=2;failure<=4;failure++){setup(&a);a.words[SAW3_AVS_CTL/4]=(1U<<27)|1;fail_write=failure;assert(spmi_regulator_saw_set_voltage(&ra,184)==-EIO);assert(a.words[SAW3_AVS_CTL/4]==((1U<<27)|1));}
 setup(&a);a.words[SAW3_AVS_CTL/4]=(1U<<27)|1;assert(!spmi_regulator_saw_set_voltage(&ra,184));
 unsigned level=184&63;assert(a.words[SAW3_AVS_CTL/4]==((1U<<27)|1|((level-4)<<10)|(level<<17)));
 setup(&a);a.words[SAW3_AVS_CTL/4]=(1U<<27)|1;assert(spmi_regulator_saw_set_voltage(&ra,128)==-ERANGE&&writes==0);
 setup(&a);va.saw_init_delay=0x3c100c00;va.saw_initialized=false;
 assert(!spmi_regulator_saw_set_voltage(&ra,185)&&va.saw_initialized&&last_cpu==0);
 assert(a.words[0x08/4]==1&&a.words[0x34/4]==0x3c100c00);
 assert(a.words[0x40/4]==0x00030000&&a.words[0x44/4]==0x02030080);
 assert(offsets[0]==0x08&&offsets[1]==0x34&&offsets[2]==0x40&&offsets[3]==0x44&&offsets[4]==SAW3_RST);
 setup(&a);assert(!spmi_regulator_saw_set_voltage(&ra,184)&&writes==3);
 for(int failure=1;failure<=4;failure++){setup(&a);va.saw_initialized=false;fail_write=failure;assert(spmi_regulator_saw_set_voltage(&ra,185)==-EIO&&!va.saw_initialized&&writes==(unsigned)failure);}
 setup(&a);va.saw_initialized=false;a.words[SAW3_VERSION/4]=0;assert(spmi_regulator_saw_set_voltage(&ra,185)==-ENODEV&&writes==0);
 setup(&a);a.words[SAW3_ID/4]=0;assert(spmi_regulator_saw_set_voltage(&ra,185)==-ENODEV&&writes==0);
 setup(&b);vb.saw_init_delay=0x3c100c30;assert(!spmi_regulator_saw_set_voltage(&rb,185)&&vb.saw_initialized&&last_cpu==4&&b.words[0x34/4]==0x3c100c30);
 puts("PASS factory SAW v3 initialization on first manual write only; CPU0/4 timing differs; setup/version/arb failures never issue voltage command; subsequent writes preserve setup");
 puts("PASS actual SAW setter: separate A53/A57 controllers and CPUs 0/4, port-0 VSET-only writes, PMIC ACK, 50us timeout, checked I/O/IPI/range errors, AVS restoration and limits");
}
'''
p=workspace/'build/validation/saw-voltage-tests.c';p.write_text(prefix+body+main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)
oem=(workspace/'kernel_xiaomi_msm8992/drivers/soc/qcom/spm.c').read_text()
for value in ('~0x700FF','MSM_SPM_REG_SAW2_PMIC_DATA_3','dev->vctl_timeout_us','new_level == vlevel'):
 assert value in oem
print('PASS voltage-control masks, VCTL/PMIC_DATA_3 pair and acknowledgment match factory SPM path; no global SAW controller remains')
assert 'static struct regmap *saw_regmap;' not in src
