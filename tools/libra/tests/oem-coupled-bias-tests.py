# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess,re
R=Path(__file__).resolve().parents[4];src=(R/'linux/drivers/regulator/qcom-labibb-regulator.c').read_text();helpers=(R/'linux/drivers/regulator/helpers.c').read_text();panel=(R/'linux/drivers/gpu/drm/panel/panel-sharp-libra-rsp61322.c').read_text()
def fn(s,n):
 a=re.search(r'(?:static )?(?:int|void) '+n+r'\(',s).start();b=s.index('{',a);i=b+1;d=1
 while d:d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#define BIT(n) (1u<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define REG_LABIBB_STATUS1 0x08
#define REG_LABIBB_ENABLE_CTL 0x46
#define REG_LAB_IBB_EN_RDY 0x49
#define LAB_IBB_EN_RDY_EN BIT(7)
#define LABIBB_STATUS1_SC_BIT BIT(6)
#define LABIBB_STATUS1_VREG_OK_BIT BIT(7)
#define LABIBB_CONTROL_ENABLE BIT(7)
#define PMI8998_LAB_REG_BASE 0xde00
#define PMI8998_IBB_REG_BASE 0xdc00
#define PMI8998_IBB_LAB_REG_OFFSET 0x200
#define IBB_ENABLE_CTL_MASK (BIT(7)|BIT(6))
#define QCOM_LAB_TYPE 0x24
#define QCOM_IBB_TYPE 0x20
#define IBB_ENABLE_TIME 10000
#define REGULATOR_ERROR_UNDER_VOLTAGE 1
#define REGULATOR_ERROR_OVER_CURRENT 2
#define LABIBB_MAX_FATAL_COUNT 2
#define LABIBB_MAX_SC_COUNT 3
#define SC_RECOVERY_INTERVAL_MS 250
#define system_wq NULL
#define dev_info(d,...) ((void)(d),reports++)
typedef unsigned int u32;
struct device {int unused;};struct regmap {unsigned int value[0xe100];};
struct regulator_dev;struct regulator_ops {int(*enable)(struct regulator_dev*);};
struct regulator_desc {unsigned enable_reg,enable_mask,enable_val,disable_val,enable_time,vsel_reg,min_uV;bool enable_is_inverted;const struct regulator_ops *ops;};
struct regulator_dev {struct regmap*regmap;struct regulator_desc*desc;void*data;};
struct work_struct {int unused;};struct delayed_work {struct work_struct work;};
struct labibb_regulator {struct regulator_desc desc;struct regmap *regmap;struct regulator_dev*rdev;unsigned int base,type;bool coupled;unsigned int fatal_count,sc_count,sc_irq;struct delayed_work sc_recovery_work;};
static void*rdev_get_drvdata(struct regulator_dev*r){return r->data;}
static unsigned int reads,writes,reports,fail_read,fail_write,last_write,scheduled,irq_enabled;
static int regmap_read(struct regmap*m,unsigned int addr,unsigned int*v){reads++;if(fail_read==addr)return -EIO;assert(addr<ARRAY_SIZE(m->value));*v=m->value[addr];return 0;}
static int regmap_update_bits(struct regmap*m,unsigned int addr,unsigned int mask,unsigned int value){if(fail_write==addr)return -EIO;writes++;last_write=addr;assert(addr==0xdc46||addr==0xde46);m->value[addr]=(m->value[addr]&~mask)|(value&mask);return 0;}
static void usleep_range(unsigned a,unsigned b){assert(a==5000&&b==6000);}
static unsigned int msecs_to_jiffies(unsigned n){return n;}
static void mod_delayed_work(void*q,struct delayed_work*w,unsigned n){(void)q;(void)w;assert(n==250);scheduled++;}
static void enable_irq(unsigned n){assert(n==7);irq_enabled++;}
struct regulator {struct regulator_dev*rdev;};struct regulator_bulk_data {struct regulator*consumer;};struct libra_panel {struct regulator_bulk_data supplies[2];};
'''
body='\n'.join(fn(helpers,n) for n in ['regulator_is_enabled_regmap','regulator_enable_regmap','regulator_disable_regmap'])
body+='\n'+'\n'.join(fn(src,n) for n in ['qcom_labibb_read_coupling','qcom_labibb_configure_enable','qcom_labibb_get_error_flags','qcom_labibb_check_sc_status','qcom_labibb_sc_recovery_worker'])
body+=r'''
static int regulator_is_enabled(struct regulator*r){return regulator_is_enabled_regmap(r->rdev);}
static int regulator_get_error_flags(struct regulator*r,unsigned int*f){return qcom_labibb_get_error_flags(r->rdev,f);}
'''+fn(panel,'libra_panel_bias_ready')
main=r'''
static struct regmap mem;static const struct regulator_ops ops={.enable=regulator_enable_regmap};
static struct labibb_regulator lab,ibb;static struct regulator_dev lrd,ird;static struct regulator lr,ir;static struct libra_panel panel;
static void reset(void){
 memset(&mem,0,sizeof(mem));reads=writes=reports=fail_read=fail_write=last_write=scheduled=irq_enabled=0;
 lab=(struct labibb_regulator){.base=0xde00,.type=QCOM_LAB_TYPE,.regmap=&mem,.sc_irq=7,.desc={.enable_reg=0xde46,.enable_mask=0x80,.enable_val=0x80,.enable_time=2000,.vsel_reg=0xde41,.min_uV=4600000,.ops=&ops}};
 ibb=(struct labibb_regulator){.base=0xdc00,.type=QCOM_IBB_TYPE,.regmap=&mem,.sc_irq=7,.desc={.enable_reg=0xdc46,.enable_mask=0xc0,.enable_val=0x80,.enable_time=10000,.vsel_reg=0xdc41,.min_uV=1400000,.ops=&ops}};
 lrd=(struct regulator_dev){&mem,&lab.desc,&lab};ird=(struct regulator_dev){&mem,&ibb.desc,&ibb};lab.rdev=&lrd;ibb.rdev=&ird;lr.rdev=&lrd;ir.rdev=&ird;panel=(struct libra_panel){.supplies={{&lr},{&ir}}};
 mem.value[0xde49]=0x80;mem.value[0xdc46]=0x80;mem.value[0xde08]=mem.value[0xdc08]=0x80;mem.value[0xde41]=mem.value[0xdc41]=0x89;
}
int main(void){
 bool coupled=false;
 reset();assert(!regulator_is_enabled_regmap(&lrd)&&!libra_panel_bias_ready(&panel));assert(!qcom_labibb_read_coupling(&mem,&coupled)&&coupled&&!writes&&!reports);
 qcom_labibb_configure_enable(&lab,coupled);struct regulator_desc before=ibb.desc;qcom_labibb_configure_enable(&ibb,coupled);assert(!memcmp(&before,&ibb.desc,sizeof(before)));assert(lab.desc.enable_reg==0xdc46&&lab.desc.enable_mask==0xc0&&lab.desc.enable_time==10000&&lab.desc.vsel_reg==0xde41&&lab.desc.min_uV==4600000);
 assert(regulator_is_enabled_regmap(&lrd)==1&&regulator_is_enabled_regmap(&ird)==1&&libra_panel_bias_ready(&panel)==1&&!writes);
 // Both live VREG_OK bits still required, despite common enable ownership.
 mem.value[0xde08]=0;assert(libra_panel_bias_ready(&panel)==0);mem.value[0xde08]=0xc0;assert(libra_panel_bias_ready(&panel)==-EIO);mem.value[0xde08]=0x80;mem.value[0xdc08]=0;assert(!libra_panel_bias_ready(&panel));mem.value[0xdc08]=0x80;
 fail_read=0xde08;assert(libra_panel_bias_ready(&panel)==-EIO);fail_read=0xdc46;assert(regulator_is_enabled_regmap(&lrd)==-EIO);fail_read=0;
 // Actual regmap helpers: no direct LAB enable/disable or voltage writes.
 assert(!regulator_disable_regmap(&lrd));assert(!regulator_is_enabled_regmap(&lrd)&&!regulator_is_enabled_regmap(&ird)&&last_write==0xdc46&&mem.value[0xde46]==0);
 assert(!regulator_enable_regmap(&lrd)&&regulator_is_enabled_regmap(&ird)&&last_write==0xdc46);assert(!regulator_disable_regmap(&ird)&&!regulator_is_enabled_regmap(&lrd));assert(!regulator_enable_regmap(&ird)&&regulator_is_enabled_regmap(&lrd));assert(mem.value[0xde41]==0x89&&mem.value[0xdc41]==0x89&&mem.value[0xde46]==0);
 fail_write=0xdc46;assert(regulator_enable_regmap(&lrd)==-EIO&&regulator_disable_regmap(&lrd)==-EIO);fail_write=0;
 // Coupled SCP recovery uses common IBB command even with LAB_CTL=0.
 writes=scheduled=irq_enabled=0;qcom_labibb_sc_recovery_worker(&lab.sc_recovery_work.work);assert(writes==1&&!scheduled&&irq_enabled==1&&last_write==0xdc46);
 mem.value[0xdc46]=0;writes=scheduled=irq_enabled=0;qcom_labibb_sc_recovery_worker(&ibb.sc_recovery_work.work);assert(!writes&&scheduled==1&&!irq_enabled);
 mem.value[0xdc46]=0x80;mem.value[0xde08]=0xc0;writes=scheduled=irq_enabled=0;qcom_labibb_sc_recovery_worker(&lab.sc_recovery_work.work);assert(!writes&&scheduled==1&&!irq_enabled);mem.value[0xde08]=0x80;
 // Standalone/PMI8998 descriptor and SCP gate unchanged.
 reset();before=lab.desc;qcom_labibb_configure_enable(&lab,false);assert(!memcmp(&before,&lab.desc,sizeof(before))&&!lab.coupled);qcom_labibb_sc_recovery_worker(&lab.sc_recovery_work.work);assert(!writes&&scheduled==1&&!irq_enabled);assert(!regulator_enable_regmap(&lrd)&&last_write==0xde46);
 reset();coupled=false;fail_read=0xde49;assert(qcom_labibb_read_coupling(&mem,&coupled)==-EIO&&!writes&&!reports);
 reset();mem.value[0xde49]=0;coupled=true;assert(!qcom_labibb_read_coupling(&mem,&coupled)&&!coupled&&!writes);
 puts("PASS actual bias helpers + panel status: coupled firmware LAB_CTL=0/IBB_CTL=0x80 old rejection reproduced, shared IBB control recognized, both VREG_OK/SC/read errors checked, LAB/IBB enable-disable share IBB without voltage writes, coupled SCP recovery and standalone path verified; coupling read error returns without writes.");
}
'''
p=R/'build/validation/oem-coupled-bias-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(prefix+body+main);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
oem=(R/'kernel_xiaomi_msm8992/drivers/regulator/qpnp-labibb-regulator.c').read_text();a=oem.index('static int qpnp_labibb_regulator_enable(');b=oem.index('static int qpnp_lab_regulator_enable(',a);paired=oem[a:b];assert 'labibb->ibb_base + REG_IBB_ENABLE_CTL' in paired and 'labibb->lab_base + REG_LAB_ENABLE_CTL' not in paired;assert 'REG_LAB_STATUS1' in paired and 'REG_IBB_STATUS1' in paired
assert 'if (ibb_en_rdy_val == LAB_IBB_EN_RDY_EN)' in oem
probe=src[src.index('static int qcom_labibb_regulator_probe('):];assert probe.index('qcom_labibb_read_coupling(')<probe.index('devm_regulator_register(');assert 'of_device_is_compatible(dev->of_node, "qcom,pmi8994-lab-ibb")' in probe
print('PASS paired control/readiness checked against OEM; hardware mode detection precedes registration and is restricted to PMI8994')
