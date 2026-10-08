# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[4];s=(R/'linux/drivers/gpu/drm/msm/dsi/dsi_host.c').read_text()
def fn(name):
 a=s.index('static ',s.index(name+'(')-60);b=s.index('{',a);i=b+1;d=1
 while d:d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#define DSI_BUS_CLK_MAX 4
#define REG_DSI_6G_HW_VERSION 0x1f4
#define MSM_DSI_VER_MAJOR_6G 3
#define ERR_PTR(n) ((void*)(intptr_t)(n))
#define dev_dbg(...) ((void)0)
struct device {void *of_node;};struct platform_device {struct device dev;};
struct clk_bulk_data {const char *id;};struct msm_dsi_config {int num_bus_clks,num_regulators;const char **bus_clk_names;void *regulator_data;};
struct msm_dsi_cfg_handler {const struct msm_dsi_config *cfg;};
struct msm_dsi_host {struct platform_device*pdev;void *supplies;char *ctrl_base;unsigned int bootstrap_num_supplies;bool bootstrap_supplies_on;};
static int failure,regrefs,pmrefs,clkrefs,reads,disables,handles;static void(*action)(void*);static void *action_data;static const struct msm_dsi_config *expected;
static int clk_bulk_get(struct device*d,int n,struct clk_bulk_data*c){(void)d;(void)c;assert(n==3);if(failure==1)return -EIO;handles++;return 0;}
static void clk_bulk_put(int n,struct clk_bulk_data*c){(void)c;assert(n==3&&handles==1&&!clkrefs);handles--;}
static int devm_regulator_bulk_get_const(struct device*d,int n,void*v,void**s){(void)d;(void)v;assert(n==4);*s=(void*)1;return failure==2?-EIO:0;}
static int pm_runtime_resume_and_get(struct device*d){(void)d;if(failure==3)return -EIO;pmrefs++;return 0;}
static int regulator_bulk_enable(int n,void*s){assert(n==4&&s&&(pmrefs==1));if(failure==4)return -EIO;regrefs++;return 0;}
static int regulator_bulk_disable(int n,void*s){assert(n==4&&s&&regrefs==1);regrefs--;disables++;return 0;}
static int clk_bulk_prepare_enable(int n,struct clk_bulk_data*c){(void)c;assert(n==3&&regrefs==1&&pmrefs==1);if(failure==5)return -EIO;clkrefs++;return 0;}
static void clk_bulk_disable_unprepare(int n,struct clk_bulk_data*c){(void)c;assert(n==3&&clkrefs==1);clkrefs--;}
static unsigned int readl(void *p){(void)p;assert(clkrefs==1&&pmrefs==1&&regrefs==1);reads++;return 0x10030000;}
static const struct msm_dsi_cfg_handler *msm_dsi_cfg_get(int major,unsigned int minor,void*np){(void)np;assert(major==3&&minor==0x10030000);static struct msm_dsi_cfg_handler h;h.cfg=failure==6?NULL:expected;return &h;}
static int devm_add_action_or_reset(struct device*d,void(*fn)(void*),void*data){(void)d;if(failure==7){fn(data);return -ENOMEM;}action=fn;action_data=data;return 0;}
static void pm_runtime_put_sync(struct device*d){(void)d;assert(pmrefs==1);pmrefs--;}
'''
# Match the actual scalar type alias used by the kernel function.
prefix+='typedef unsigned int u32;\n'
body=fn('dsi_bootstrap_supplies_release')+'\n'+fn('dsi_get_config_8992')
main=r'''
int main(void){
 const char *names[]={"a","b","c"};struct msm_dsi_config cfg={.num_bus_clks=3,.num_regulators=4,.bus_clk_names=names};struct platform_device p={0};char mem[0x200];expected=&cfg;
 for(failure=0;failure<=7;failure++){
  struct msm_dsi_host h={.pdev=&p,.ctrl_base=mem};regrefs=pmrefs=clkrefs=reads=disables=0;action=NULL;action_data=NULL;
  const struct msm_dsi_cfg_handler *result=dsi_get_config_8992(&h,&cfg); assert(!handles);
  if(!failure){assert(result&&result->cfg==&cfg&&regrefs==1&&!pmrefs&&!clkrefs&&reads==1&&h.bootstrap_supplies_on&&!disables&&action);action(action_data);assert(!regrefs&&!h.bootstrap_supplies_on&&disables==1);action(action_data);assert(disables==1);}
  else{assert((intptr_t)result<0&&!regrefs&&!pmrefs&&!clkrefs&&!h.bootstrap_supplies_on);assert(disables==(failure>=5));}
 }
 // Ownership transferred to power_on: deferred devres release is a no-op.
 failure=0;struct msm_dsi_host h={.pdev=&p,.ctrl_base=mem};regrefs=pmrefs=clkrefs=reads=disables=0;assert((intptr_t)dsi_get_config_8992(&h,&cfg)>0);h.bootstrap_supplies_on=false;action(action_data);assert(regrefs==1&&!disables);regulator_bulk_disable(4,h.supplies);assert(!regrefs&&disables==1);
 puts("PASS actual MSM8992 discovery: supplies remain voted through successful discovery, bus clocks/PM drop, all seven failures balance references, abandoned probe cleanup once, normal power ownership prevents devres double-disable.");
}
'''
p=R/'build/validation/oem-bootstrap-power-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(prefix+body+main);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
