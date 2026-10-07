#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise real PMI8994 SRAM transactions and OEM numeric formats."""
from pathlib import Path
import re
import subprocess

workspace = Path(__file__).resolve().parents[4]
driver = (workspace / 'linux/drivers/power/supply/qcom_pmi8994_battery.c').read_text()
header = (workspace / 'linux/drivers/power/supply/qcom_pmi8994_battery.h').read_text()
oem_fg = (workspace / 'kernel_xiaomi_msm8992/drivers/power/qpnp-fg.c').read_text()
oem_chg = (workspace / 'kernel_xiaomi_msm8992/drivers/power/qpnp-smbcharger.c').read_text()
validation = workspace / 'build/validation'
validation.mkdir(exist_ok=True)

def function(source, name):
    m = re.search(r'static (?:int|void|bool) ' + name + r'\(', source)
    return source[m.start():source.index('\n}\n', m.start()) + 3]

# The current codes are the hardware's non-linear OEM table, not linear mA.
old = re.search(r'static const int usb_current_table\[\] = \{(.*?)\};', oem_chg, re.S)
new = re.search(r'static const int pmi8994_current_ma\[\] = \{(.*?)\};', header, re.S)
assert re.findall(r'\d+', old[1]) == re.findall(r'\d+', new[1])
for name, value in [('LSB_16B_NUMRTR', '152587'), ('LSB_16B_DENMTR', '1000'), ('TEMP_LSB_16B', '625'), ('DECIKELVIN', '2730')]:
    assert re.search(r'#define\s+' + name + r'\s+' + value + r'\b', oem_fg)
for name, addr, offset in [('VOLTAGE', '5CC', 1), ('CURRENT', '5CC', 3), ('BATT_TEMP', '550', 2)]:
    assert re.search(r'DATA\(' + name + r',\s+0x' + addr + r',\s+' + str(offset), oem_fg)

prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8;typedef uint16_t u16;typedef int16_t s16;typedef uint64_t u64;typedef int64_t s64;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((1U<<((h)-(l)+1))-1)<<(l))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define DIV_ROUND_CLOSEST(a,b) (((a)+(b)/2)/(b))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define div_s64(a,b) ((a)/(b))
enum {POWER_SUPPLY_STATUS_UNKNOWN,POWER_SUPPLY_STATUS_CHARGING,POWER_SUPPLY_STATUS_DISCHARGING,POWER_SUPPLY_STATUS_NOT_CHARGING,POWER_SUPPLY_STATUS_FULL};
enum {POWER_SUPPLY_HEALTH_GOOD,POWER_SUPPLY_HEALTH_OVERHEAT,POWER_SUPPLY_HEALTH_COLD,POWER_SUPPLY_HEALTH_WARM,POWER_SUPPLY_HEALTH_COOL};
enum power_supply_property {POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR};
enum {POWER_SUPPLY_CHARGE_BEHAVIOUR_AUTO,POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE};
struct regmap {u8 regs[65536],sram[4096];unsigned address;int count,fail,timeout;bool requested,cleanup,changed;};
struct mutex {int unused;}; struct delayed_work {int unused;};
struct pmi8994_snapshot {int voltage,current_ua,temp,full_design;};
struct pmi8994_battery {struct regmap*map;struct mutex lock;struct delayed_work update;unsigned fcc_ceiling,automatic_cmd;};
struct power_supply {struct pmi8994_battery*b;}; union power_supply_propval {int intval;};
static void*power_supply_get_drvdata(struct power_supply*p){return p->b;}
static void mutex_lock(struct mutex*m){(void)m;}static void mutex_unlock(struct mutex*m){(void)m;}
#define local_irq_save(x) ((x)=0)
#define local_irq_restore(x) ((void)(x))
static int system_wq;
static void mod_delayed_work(int wq,struct delayed_work*w,int when){(void)wq;(void)w;(void)when;}
static void put_unaligned_le16(unsigned v,u8*p){p[0]=v;p[1]=v>>8;}
static unsigned get_unaligned_le16(u8*p){return p[0]|(p[1]<<8);}
static int fault(struct regmap*m){return ++m->count==m->fail?-EIO:0;}
static int regmap_read(struct regmap*m,unsigned r,unsigned*v){int e=fault(m);if(!e)*v=m->regs[r];return e;}
static int regmap_write(struct regmap*m,unsigned r,unsigned v){
 assert(r==0x4441||r==0x10d0);int e=fault(m);if(e)return e;
 if(r==0x4441)assert(!(v&BIT(6)));m->regs[r]=v;return 0;}
static int regmap_update_bits(struct regmap*m,unsigned r,unsigned mask,unsigned v){
 assert(r==0x4440||r==0x1242||r==0x10f2);int e=fault(m);if(e)return e;
 m->regs[r]=(m->regs[r]&~mask)|(v&mask);if(r==0x4440){m->requested=!!(v&BIT(7));if(!m->requested)m->cleanup=true;}else m->changed=true;return 0;}
static int poll(struct regmap*m,unsigned*v){int e=fault(m);if(e)return e;if(m->timeout)return -ETIMEDOUT;*v=1;return 0;}
#define regmap_read_poll_timeout(map,r,v,c,d,t) poll(map,&v)
static int regmap_bulk_write(struct regmap*m,unsigned r,u8*p,size_t n){assert(r==0x4442&&n==2&&m->requested);int e=fault(m);if(!e)m->address=get_unaligned_le16(p);return e;}
static int regmap_bulk_read(struct regmap*m,unsigned r,u8*p,size_t n){assert(r>=0x444c&&r+n<=0x4450&&m->requested);int e=fault(m);if(!e)memcpy(p,m->sram+m->address+r-0x444c,n);return e;}
'''
defines = '\n'.join(re.findall(r'^#define (?:MEM_\w+|CHGR_FCC|BAT_CMD|BAT_DISABLE)\s+.*$', driver, re.M))
main = r'''
static void init(struct regmap*m){memset(m,0,sizeof(*m));m->sram[0x53c]=1;
 put_unaligned_le16(0x6198,m->sram+0x5cd);put_unaligned_le16(0x0eb0,m->sram+0x5cf);
 put_unaligned_le16(0x13a0,m->sram+0x552);put_unaligned_le16(3071,m->sram+0x4f4);}
int main(void){
 for(unsigned v=0;v<=65535;v++){
  assert(pmi8994_voltage(v)==(int)((uint64_t)v*152587/1000));
  int signed_v=v>=32768?(int)v-65536:v;
  assert(pmi8994_current(v)==-(int)((int64_t)signed_v*152587/1000));
  assert(pmi8994_temperature(v)==signed_v*625/1000-2730);
 }
 for(unsigned v=0;v<256;v++)assert(pmi8994_capacity(v)==(!v?0:v==255?100:(((v-1)*98+126)/253+1)));
 assert(pmi8994_float_voltage(0x2e)==4400000);
 assert(pmi8994_status(false,0,4)==POWER_SUPPLY_STATUS_DISCHARGING);
 assert(pmi8994_status(true,0x80,0)==POWER_SUPPLY_STATUS_FULL);
 assert(pmi8994_status(true,0,8)==POWER_SUPPLY_STATUS_NOT_CHARGING);
 assert(pmi8994_status(true,0,4)==POWER_SUPPLY_STATUS_CHARGING);
 assert(pmi8994_health(5)==POWER_SUPPLY_HEALTH_OVERHEAT);
 assert(pmi8994_health(4)==POWER_SUPPLY_HEALTH_COLD);
 struct regmap m;struct pmi8994_snapshot s={0};struct pmi8994_battery b={.map=&m,.fcc_ceiling=1000000};
 init(&m);assert(!pmi8994_gauge_read(&b,&s));assert(s.voltage==3812233&&s.current_ua==-573727&&s.temp==410&&s.full_design==3071000);
 int count=m.count;assert(m.cleanup&&!m.requested&&!m.changed&&m.regs[0x4441]==0);
 /* UPower 1.90.9 overrides status to discharging when current_now < 0.
  * Raw negative current during charging must therefore become positive.
  * https://sources.debian.org/src/upower/1.90.9-1/src/linux/up-device-supply-battery.c/
  */
 init(&m);put_unaligned_le16(0xfe00,m.sram+0x5cf);assert(!pmi8994_gauge_read(&b,&s));
 assert(s.current_ua==78124&&pmi8994_status(true,0,4)==POWER_SUPPLY_STATUS_CHARGING);
 assert(pmi8994_current(0x0200)<0&&pmi8994_current(0xfe00)>0&&pmi8994_current(0)==0);
 for(int i=1;i<=count;i++){
  init(&m);m.fail=i;assert(pmi8994_gauge_read(&b,&s)==-EIO);
  if(i>=4&&i!=count)assert(!m.requested); /* last clear itself can fail */
  assert(!m.changed); /* no charger or gauge-data programming */
 }
 init(&m);m.timeout=1;assert(pmi8994_gauge_read(&b,&s)==-ETIMEDOUT&&m.cleanup&&!m.requested);
 init(&m);m.sram[0x53c]=0;assert(pmi8994_gauge_read(&b,&s)==-ENODATA&&!m.requested);
 init(&m);m.regs[0x4440]=128;assert(pmi8994_gauge_read(&b,&s)==-EBUSY&&m.count==1);
 for(unsigned a=0x500;a<0x504;a++)for(size_t n=1;n<=12;n++){
  init(&m);m.requested=true;for(unsigned i=0;i<4096;i++)m.sram[i]=i%251;
  u8 data[12];assert(!pmi8994_sram_read(&b,a,data,n));assert(!memcmp(data,m.sram+a,n));
 }
 struct power_supply psy={&b};union power_supply_propval val={.intval=1500000};
 init(&m);assert(pmi8994_battery_set(&psy,POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,&val)==-EINVAL&&!m.count);
 val.intval=500000;assert(!pmi8994_battery_set(&psy,POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,&val)&&m.regs[0x10f2]==4);
 val.intval=1000000;assert(!pmi8994_battery_set(&psy,POWER_SUPPLY_PROP_CONSTANT_CHARGE_CURRENT,&val)&&m.regs[0x10f2]==11);
 val.intval=POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE;assert(!pmi8994_battery_set(&psy,POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR,&val)&&m.regs[0x1242]==2);
 val.intval=POWER_SUPPLY_CHARGE_BEHAVIOUR_AUTO;assert(!pmi8994_battery_set(&psy,POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR,&val)&&m.regs[0x1242]==0);
 b.automatic_cmd=2;assert(!pmi8994_battery_set(&psy,POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR,&val)&&m.regs[0x1242]==2);
 puts("PASS OEM gauge conversions across all raw16/SOC values; real SRAM cross-word reads, timeout and every transaction fault; no profile/temperature writes; current ceiling and inhibit/restore callbacks");
}
'''
source = validation / 'battery-model.c'
source.write_text(prefix + header + defines + '\n' +
                  function(driver, 'pmi8994_sram_read') +
                  function(driver, 'pmi8994_gauge_read') +
                  function(driver, 'pmi8994_battery_set') + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
                '-Wno-misleading-indentation', str(source), '-o', str(source.with_suffix(''))], check=True)
subprocess.run([str(source.with_suffix(''))], check=True)

dtb = workspace / 'build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb'
node = '/soc@0/spmi@fc4cf000/pmic@2/battery@4000'
# Resolve the actual controller path rather than assuming its naming.
paths = subprocess.check_output(['fdtdump', str(dtb)], text=True, stderr=subprocess.DEVNULL)
assert 'battery@4000' in paths and 'qcom,pmi8994-battery' in paths
cfg = (workspace / 'build/libra/.config').read_text()
assert 'CONFIG_BATTERY_QCOM_PMI8994=y' in cfg
assert (workspace / 'cfg/msm8992-libra.config').read_bytes() == (workspace / 'linux/tools/libra/cfg/msm8992-libra.config').read_bytes()
print('PASS native battery node and built-in configuration, inherited charger policy and source mirrors')
