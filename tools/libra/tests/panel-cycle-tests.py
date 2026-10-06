# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import re,subprocess
R=Path(__file__).resolve().parents[4];panel=(R/'linux/drivers/gpu/drm/panel/panel-sharp-libra-rsp61322.c').read_text();core=(R/'linux/drivers/gpu/drm/drm_panel.c').read_text()
def fn(s,n):
 m=re.search(r'(?:static )?int '+n+r'\(',s);a=m.start();b=s.index('{',a);depth=1;i=b+1
 while depth:depth+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
old=subprocess.check_output(['git','show','5e21ae4dc789c31ba227264f3cc2e56052308ebd:drivers/gpu/drm/panel/panel-sharp-libra-rsp61322.c'],cwd=R/'linux',text=True)
prefix=r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>
struct device {int unused;};struct mipi_dsi_device {struct device dev;};
struct drm_panel;struct drm_panel_funcs {int(*prepare)(struct drm_panel*),(*enable)(struct drm_panel*),(*disable)(struct drm_panel*),(*unprepare)(struct drm_panel*);};
struct drm_panel {const struct drm_panel_funcs*funcs;bool prepared,enabled;int follower_lock,followers;void *dev,*backlight;};
struct follower_funcs {int(*panel_prepared)(void*),(*panel_unpreparing)(void*);};struct drm_panel_follower {const struct follower_funcs *funcs;};
struct libra_panel {struct drm_panel panel;struct mipi_dsi_device *dsi;int supplies[2];void *reset,*enable;};
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define list_for_each_entry(f,h,l) for((void)(h),f=NULL;f!=NULL;)
static int errors,warnings,power,prepare_count,command_count,fail_command,fail_power;static bool timing_on,light;static const int libra_off[2]={0x28,0x10};
static void mutex_lock(int*l){assert((*l)++==0);}static void mutex_unlock(int*l){assert((*l)--==1);}
#define dev_info(...) ((void)0)
#define dev_warn(...) (warnings++)
#define dev_err(...) (errors++)
#define DRM_DEV_INFO(...) (errors++)
static int backlight_enable(void*b){(void)b;light=true;return 0;}static int backlight_disable(void*b){(void)b;light=false;return 0;}
static int libra_panel_commands(struct libra_panel*c,const int*cmds,size_t n,bool lp){(void)c;assert(cmds==libra_off&&n==2&&!lp);command_count++;return !timing_on||fail_command?-ETIMEDOUT:0;}
static void gpiod_set_value_cansleep(void*p,int v){(void)p;(void)v;assert(power);}
static int regulator_bulk_disable(int n,int*s){(void)s;assert(n==2&&power);if(fail_power)return -EIO;power=0;return 0;}
static int mock_prepare(struct drm_panel*p){(void)p;assert(!power);prepare_count++;power=1;return 0;}
'''
funcs='\n'.join(fn(core,n) for n in ['drm_panel_prepare','drm_panel_enable','drm_panel_disable','drm_panel_unprepare'])
funcs+='\n'+fn(old,'libra_panel_unprepare').replace('libra_panel_unprepare','old_unprepare')
funcs+='\n'+fn(panel,'libra_panel_disable')+'\n'+fn(panel,'libra_panel_unprepare')
main=r'''
int main(void){
 struct mipi_dsi_device dsi={0};struct libra_panel p={.dsi=&dsi};const struct drm_panel_funcs old={.prepare=mock_prepare,.unprepare=old_unprepare},fixed={.prepare=mock_prepare,.disable=libra_panel_disable,.unprepare=libra_panel_unprepare};
 p.panel.funcs=&old;assert(!drm_panel_prepare(&p.panel));assert(!drm_panel_enable(&p.panel));timing_on=false;assert(!drm_panel_disable(&p.panel));assert(drm_panel_unprepare(&p.panel)==-ETIMEDOUT);assert(!power&&p.panel.prepared);assert(!drm_panel_prepare(&p.panel));assert(prepare_count==1&&warnings==1&&!power);
 // Correct helper order: bridge disable, encoder timing off, bridge post-disable.
 for(int failure=0;failure<=1;failure++){
  p.panel=(struct drm_panel){.funcs=&fixed};prepare_count=command_count=errors=warnings=0;power=0;fail_command=0;fail_power=0;timing_on=true;
  assert(!drm_panel_prepare(&p.panel));assert(!drm_panel_enable(&p.panel));fail_command=failure;
  assert(!drm_panel_disable(&p.panel));assert(command_count==1&&!p.panel.enabled&&!light);assert(errors==failure);
  timing_on=false;assert(!drm_panel_unprepare(&p.panel));assert(!p.panel.prepared&&!power&&command_count==1);
  fail_command=0;timing_on=true;assert(!drm_panel_prepare(&p.panel));assert(prepare_count==2&&power);assert(!drm_panel_enable(&p.panel));assert(!drm_panel_disable(&p.panel));timing_on=false;assert(!drm_panel_unprepare(&p.panel));assert(!power&&!warnings);
 }
 p.panel=(struct drm_panel){.funcs=&fixed};assert(!drm_panel_prepare(&p.panel));fail_power=1;assert(drm_panel_unprepare(&p.panel)==-EIO);assert(p.panel.prepared&&power);fail_power=0;assert(!drm_panel_unprepare(&p.panel));assert(!p.panel.prepared&&!power);
 puts("PASS actual DRM panel core/callbacks: reproduced stale prepared state after v40 timeout; HS shutdown before encoder stop; TX error logged without preventing reset/power-off; repeated prepare resumes; regulator failure remains reported.");
}
'''
# Pin integration ordering to the kernel helper used by this device.
s=(R/'linux/drivers/gpu/drm/drm_atomic_helper.c').read_text();a=s.index('disable_outputs(');s=s[a:s.index('\nstatic',a)]
assert s.index('drm_atomic_bridge_chain_disable(')<s.index('funcs->atomic_disable(encoder')<s.index('drm_atomic_bridge_chain_post_disable(')
assert '.disable = libra_panel_disable' in panel
p=R/'build/validation/panel-cycle-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(prefix+funcs+main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
