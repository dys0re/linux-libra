# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess,re
R=Path(__file__).resolve().parents[4];src=(R/'linux/drivers/gpu/drm/panel/panel-sharp-libra-rsp61322.c').read_text()
def fn(s,n):
 a=re.search(r'static (?:int|bool) '+n+r'\(',s).start();b=s.index('{',a);i=b+1;d=1
 while d:d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define REGULATOR_ERROR_UNDER_VOLTAGE 1
#define dev_err(...) ((void)0)
struct drm_panel {int unused;};struct mipi_dsi_device {int dev;};
struct regulator {int enabled,flags,error;};struct regulator_bulk_data {struct regulator *consumer;};
struct gpio_desc {int direction,value,read_error;};
struct libra_panel {struct drm_panel panel;struct mipi_dsi_device *dsi;struct regulator_bulk_data supplies[2];struct gpio_desc *reset,*enable;bool firmware_prepared;};
static int votes,commands,fail_enable,fail_direction,fail_command,gpio_writes;static int polls,direction_reads;static const int libra_on[14]={0};
static int regulator_is_enabled(struct regulator *r){return r->enabled;}
static int regulator_get_error_flags(struct regulator *r,unsigned int *f){*f=r->flags;return r->error;}
static int gpiod_get_direction(struct gpio_desc *g){direction_reads++;return g->direction;}
static int gpiod_get_value_cansleep(struct gpio_desc *g){return g->read_error?g->read_error:g->value;}
static int regulator_bulk_enable(int n,struct regulator_bulk_data *r){assert(n==2&&!votes);if(fail_enable)return -EIO;votes++;for(int i=0;i<n;i++)r[i].consumer->enabled=1;return 0;}
static int regulator_bulk_disable(int n,struct regulator_bulk_data *r){assert(n==2&&votes==1);votes--;for(int i=0;i<n;i++)r[i].consumer->enabled=0;return 0;}
static int gpiod_direction_output(struct gpio_desc *g,int v){gpio_writes++;if(fail_direction)return -EIO;g->direction=0;g->value=v;return 0;}
static void gpiod_set_value_cansleep(struct gpio_desc *g,int v){gpio_writes++;g->value=v;}
static void usleep_range(unsigned int a,unsigned int b){assert((a==5000&&b==6000)||(a==10000&&b==11000));}
static int libra_panel_commands(struct libra_panel *c,const int *cmd,size_t n,bool lp){(void)c;assert(cmd==libra_on&&n==14&&lp);commands++;return fail_command?-ETIMEDOUT:0;}
#define read_poll_timeout(op,val,cond,interval,timeout,sleep,ctx) ((void)(interval),(void)(timeout),(void)(sleep),polls++,(val)=op(ctx),(cond)?0:-ETIMEDOUT)
'''
body='\n'.join(fn(src,n) for n in ['libra_panel_bias_ready','libra_panel_firmware_ready','libra_panel_prepare','libra_panel_unprepare'])
main=r'''
static struct regulator rails[2];static struct gpio_desc rst,en;static struct mipi_dsi_device dsi;static struct libra_panel p;
static void reset(void){votes=commands=gpio_writes=polls=direction_reads=0;fail_enable=fail_direction=fail_command=0;rails[0]=rails[1]=(struct regulator){.enabled=1};rst=(struct gpio_desc){.direction=0,.value=0};en=(struct gpio_desc){.direction=0,.value=1};p=(struct libra_panel){.dsi=&dsi,.reset=&rst,.enable=&en,.supplies={{&rails[0]},{&rails[1]}},.firmware_prepared=true};}
int main(void){
 reset();assert(!libra_panel_prepare(&p.panel));assert(votes==1&&!commands&&!gpio_writes&&!p.firmware_prepared&&direction_reads==2);assert(!libra_panel_unprepare(&p.panel));assert(!votes&&rst.value==1&&en.value==0);assert(!libra_panel_prepare(&p.panel));assert(commands==1&&votes==1&&rst.value==0&&en.value==1);assert(!libra_panel_unprepare(&p.panel));
 for(int reason=0;reason<9;reason++){
  reset();switch(reason){case 0:p.firmware_prepared=false;break;case 1:rst.direction=1;break;case 2:en.direction=1;break;case 3:rst.value=1;break;case 4:en.value=0;break;case 5:rst.read_error=-EIO;break;case 6:rails[0].enabled=0;break;case 7:rails[1].enabled=0;break;case 8:en.direction=-524;break;}
  assert(!libra_panel_prepare(&p.panel));assert(commands==1&&votes==1&&gpio_writes==4&&!p.firmware_prepared);assert(!libra_panel_unprepare(&p.panel));
 }
 reset();rails[0].flags=REGULATOR_ERROR_UNDER_VOLTAGE;assert(libra_panel_prepare(&p.panel)==-ETIMEDOUT);assert(!votes&&!gpio_writes&&!commands);
 reset();rails[1].flags=2;assert(libra_panel_prepare(&p.panel)==-EIO);assert(!votes&&!gpio_writes&&!commands);
 reset();rails[0].error=-EIO;assert(libra_panel_prepare(&p.panel)==-EIO);assert(!votes&&!gpio_writes&&!commands);
 reset();fail_enable=1;assert(libra_panel_prepare(&p.panel)==-EIO&&!votes&&!p.firmware_prepared&&!gpio_writes);
 reset();p.firmware_prepared=false;fail_direction=1;assert(libra_panel_prepare(&p.panel)==-EIO&&!votes&&!commands);
 reset();p.firmware_prepared=false;fail_command=1;assert(libra_panel_prepare(&p.panel)==-ETIMEDOUT&&!votes&&rst.value==1&&en.value==0);
 puts("PASS actual panel prepare: checked firmware rails/GPIOs, no reset/on packets for one-time preservation, native power-off ownership, later cold prepare, invalid state fallback and power/GPIO/command failure cleanup.");
}
'''
p=R/'build/validation/oem-panel-handoff-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(prefix+body+main);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
oem=(R/'kernel_xiaomi_msm8992/drivers/video/msm/mdss/mdss_dsi_panel.c').read_text();assert 'if (!pinfo->cont_splash_enabled)' in oem
factory=(R/'build/factory-libra-reference.dts').read_text();assert 'qcom,cont-splash-enabled' in factory
assert 'GPIOD_ASIS' in src and 'ctx->firmware_prepared = firmware_handoff;' in src
print('PASS checked OEM cont-splash reset gate and factory property; no voltage/trim/reset waveform change')
