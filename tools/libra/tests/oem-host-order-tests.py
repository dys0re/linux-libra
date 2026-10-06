# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import subprocess,re
R=Path(__file__).resolve().parents[4];path='drivers/gpu/drm/msm/dsi/dsi_host.c';s=(R/'linux'/path).read_text();old=subprocess.check_output(['git','show','5e21ae4dc789c31ba227264f3cc2e56052308ebd:'+path],cwd=R/'linux',text=True)
def fn(source,name):
 a=source.index('int '+name+'(');b=source.index('{',a);depth=1;i=b+1
 while depth:depth+=(source[i]=='{')-(source[i]=='}');i+=1
 return source[a:i]
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define MIPI_DSI_MODE_VIDEO 1
#define DBG(...) ((void)0)
#define pr_err(...) ((void)0)
#define dev_info_once(...) ((void)0)
struct node {bool target;};struct device {struct node *of_node;};struct platform_device {struct device dev;};struct mipi_dsi_host {int dummy;};struct msm_dsi_phy {int dummy;};struct msm_dsi_phy_shared_timings {bool byte_intf_clk_div_2;};
struct msm_dsi_host;struct ops {int(*link_clk_set_rate)(struct msm_dsi_host*),(*link_clk_enable)(struct msm_dsi_host*);void(*link_clk_disable)(struct msm_dsi_host*);};struct cfg {int num_regulators;};struct msm_dsi_cfg_handler {const struct ops *ops;const struct cfg *cfg;};
struct msm_dsi_host {struct mipi_dsi_host base;struct platform_device*pdev;const struct msm_dsi_cfg_handler*cfg_hnd;int dev_mutex;bool power_on,byte_intf_clk_div_2,bootstrap_supplies_on;int mode_flags;void*supplies;};
#define to_msm_dsi_host(p) ((struct msm_dsi_host*)(p))
static char trace[64];static unsigned ntrace;static int failure,regrefs,pmrefs,clkrefs;static bool configured;
static void record(char c){assert(ntrace<63);trace[ntrace++]=c;trace[ntrace]=0;}
static bool of_device_is_compatible(struct node*n,const char*s){assert(!strcmp(s,"qcom,msm8992-dsi-ctrl"));return n->target;}
static void mutex_lock(int*p){assert((*p)++==0);}static void mutex_unlock(int*p){assert((*p)--==1);}
static void msm_dsi_sfpb_config(struct msm_dsi_host*h,bool on){(void)h;assert(on);}
static int regulator_bulk_enable(int n,void*s){(void)s;assert(n==4);record('R');if(failure==1)return -EIO;regrefs++;return 0;}
static int regulator_bulk_disable(int n,void*s){(void)s;assert(n==4&&regrefs==1);record('r');regrefs--;return 0;}
static int pm_runtime_resume_and_get(struct device*d){(void)d;record('P');if(failure==2)return -ENXIO;pmrefs++;return 0;}
static void pm_runtime_put(struct device*d){(void)d;assert(pmrefs==1);record('p');pmrefs--;}
static int rate(struct msm_dsi_host*h){(void)h;assert(regrefs&&pmrefs);record('F');return failure==3?-ERANGE:0;}
static int clocks_on(struct msm_dsi_host*h){(void)h;record('E');if(failure==4)return -EIO;clkrefs++;return 0;}
static void clocks_off(struct msm_dsi_host*h){(void)h;assert(clkrefs==1);record('e');clkrefs--;}
static int pinctrl_pm_select_default_state(struct device*d){(void)d;record('A');return failure==5?-EINVAL:0;}
static void dsi_timing_setup(struct msm_dsi_host*h,bool bonded){(void)h;assert(!bonded&&pmrefs);record('T');}
static void dsi_ctrl_enable(struct msm_dsi_host*h,struct msm_dsi_phy_shared_timings*t,struct msm_dsi_phy*p){(void)h;(void)t;(void)p;assert(pmrefs);record('C');configured=true;}
static void dsi_op_mode_config(struct msm_dsi_host*h,bool video,bool enable){(void)h;assert(video&&enable&&configured&&!clkrefs&&pmrefs);record('M');}
static void dsi_sw_reset(struct msm_dsi_host*h){(void)h;assert(clkrefs&&pmrefs);record('S');}
static void dsi_ctrl_disable(struct msm_dsi_host*h){(void)h;assert(configured&&pmrefs);record('X');configured=false;}
'''
body=fn(s,'msm_dsi_host_power_on')+'\n'+fn(old,'msm_dsi_host_power_on').replace('msm_dsi_host_power_on','reference_power_on')
main=r'''
static void reset(void){ntrace=0;trace[0]=0;regrefs=pmrefs=clkrefs=0;configured=false;}
int main(void){
 const struct ops op={rate,clocks_on,clocks_off};const struct cfg cfg={4};const struct msm_dsi_cfg_handler handler={&op,&cfg};struct node n={true};struct platform_device p={.dev={&n}};struct msm_dsi_host h={.pdev=&p,.cfg_hnd=&handler,.mode_flags=MIPI_DSI_MODE_VIDEO};struct msm_dsi_phy_shared_timings t={true};struct msm_dsi_phy phy;
 for(failure=0;failure<=5;failure++){
  reset();h.power_on=false;n.target=true;int ret=msm_dsi_host_power_on(&h.base,&t,false,&phy);
  if(!failure){assert(!ret&&!strcmp(trace,"RPTCMFEAS")&&h.power_on&&regrefs==1&&pmrefs==1&&clkrefs==1);}
  else{assert(ret<0&&!h.power_on&&!regrefs&&!pmrefs&&!clkrefs&&!configured);}
  assert(!h.dev_mutex);
  reset();h.power_on=false;n.target=false;ret=msm_dsi_host_power_on(&h.base,&t,false,&phy);char actual[64];strcpy(actual,trace);bool actual_on=h.power_on;int actual_refs=regrefs+pmrefs+clkrefs;
  reset();h.power_on=false;int before=reference_power_on(&h.base,&t,false,&phy);assert(before==ret&&!strcmp(actual,trace)&&actual_on==h.power_on&&actual_refs==regrefs+pmrefs+clkrefs);
 }
 for(failure=0;failure<=5;failure++){
  reset();h.power_on=false;h.bootstrap_supplies_on=true;regrefs=1;n.target=true;
  int ret=msm_dsi_host_power_on(&h.base,&t,false,&phy);
  if(failure<2){assert(!ret&&!strcmp(trace,"PTCMFEAS")&&h.power_on&&regrefs==1&&pmrefs==1&&clkrefs==1);}
  else{assert(ret<0&&!h.power_on&&!regrefs&&!pmrefs&&!clkrefs&&!configured);}
  assert(!h.bootstrap_supplies_on&&!h.dev_mutex);
 }
 reset();failure=0;h.power_on=true;n.target=true;assert(!msm_dsi_host_power_on(&h.base,&t,false,&phy)&&!ntrace&&!regrefs&&!pmrefs&&!clkrefs);
 puts("PASS actual host function: OEM target mode/controller/op setup before rates/link enable/reset; rollback disables early controller with bus power held; generic trace/errors match v35 baseline; already-on unchanged.");
}
'''
p=R/'build/validation/oem-host-order-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(prefix+body+main);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(p.with_suffix(''))],check=True);subprocess.run([str(p.with_suffix(''))],check=True)
v=(R/'kernel_xiaomi_msm8992/drivers/video/msm/mdss/mdss_dsi_host.c').read_text();a=v.index('void mdss_dsi_ctrl_setup(');b=v.index('\n/**',a);setup=v[a:b];assert setup.index('mdss_dsi_mode_setup(')<setup.index('mdss_dsi_host_init(')<setup.index('mdss_dsi_op_mode_config(')
v=(R/'kernel_xiaomi_msm8992/drivers/video/msm/mdss/mdss_dsi.c').read_text();a=v.index('int mdss_dsi_on(');b=v.index('\nint ',a+1);on=v[a:b];assert on.index('mdss_dsi_ctrl_setup(')<on.index('DSI_LINK_CLKS, 1')<on.index('mdss_dsi_sw_reset(')
print('PASS target order checked against OEM ctrl_setup/on source')
