# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import re,subprocess
R=Path(__file__).resolve().parents[4];repo=R/'linux';m=(repo/'drivers/clk/qcom/mmcc-msm8994.c').read_text();c=(repo/'drivers/clk/clk.c').read_text()
a=m.index('static int mmcc_8992_dsi_set_rate(');b=m.index('static const struct pll_vco mmpll_p_vco',a);wrappers=m[a:b]
a=m.index('\t\tbyte0_8992_init = *byte0_clk_src.clkr.hw.init;');b=m.index('\n\n\t\t/* MSM8992 features',a);profile=m[a:b]
a=c.index('static struct clk_core *__clk_set_parent_before(');b=c.index('\nstatic int __clk_set_parent(',a);reparent=c[a:b]
provider=(repo/'include/linux/clk-provider.h').read_text();flags={n:1<<int(v) for n,v in re.findall(r'#define\s+(CLK_[A-Z0-9_]+)\s+BIT\((\d+)\)',provider)}
prefix=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
typedef uint8_t u8;
struct clk_core;struct clk_hw {struct clk_core *core;};struct clk {struct clk_core *core;};
struct clk_ops {int(*set_rate)(struct clk_hw*,unsigned long,unsigned long);int(*set_rate_and_parent)(struct clk_hw*,unsigned long,unsigned long,u8);};
struct clk_init_data {unsigned long flags;const void *parent_data;const struct clk_ops *ops;};
struct clkr {struct {struct clk_init_data *init;} hw;};struct rcg {struct clkr clkr;};
struct clk_core {unsigned long flags;unsigned prepare_count,users;bool rate_ready;struct clk_core *parent;struct clk_hw *hw;};
static struct clk_init_data byte_original,pixel_original,byte0_8992_init,pclk0_8992_init;static struct clk_ops byte0_8992_ops,pclk0_8992_ops;
static struct rcg byte0_clk_src,pclk0_clk_src;static const int mmcc_8992_xo_dsibyte[]={1},mmcc_8992_xo_dsipll[]={2};
static char trace[32];static unsigned ntrace,handles,warnings,errors,updates;static int fail_prepare,fail_get,fail_update,last_index;static struct clk handle;
static void record(char c){trace[ntrace++]=c;trace[ntrace]=0;}
#define pr_err(...) (errors++)
#define ERR_PTR(e) ((void*)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p)>(uintptr_t)-4096)
#define PTR_ERR(p) ((long)(intptr_t)(p))
static struct clk_hw *clk_hw_get_parent(struct clk_hw*h){return h->core->parent?h->core->parent->hw:0;}
static struct clk *clk_hw_get_clk(struct clk_hw*h,const char*s){(void)s;if(fail_get)return ERR_PTR(fail_get);handles++;handle.core=h->core;record('G');return &handle;}
static int clk_core_prepare_enable(struct clk_core*p){if(!p)return 0;record('E');if(!p->rate_ready)return -EINVAL;if(fail_prepare)return fail_prepare;p->users++;return 0;}
static void clk_core_disable_unprepare(struct clk_core*p){if(!p)return;record('D');if(!p->users){warnings+=2;return;}p->users--;}
static int clk_prepare_enable(struct clk*i){return clk_core_prepare_enable(i->core);}
static void clk_disable_unprepare(struct clk*i){clk_core_disable_unprepare(i->core);}
static void clk_put(struct clk*i){(void)i;assert(handles);handles--;record('P');}
static unsigned long clk_enable_lock(void){return 0;}static void clk_enable_unlock(unsigned long f){(void)f;}
static void clk_reparent(struct clk_core*c,struct clk_core*p){c->parent=p;}
static void clk_core_enable_lock(struct clk_core*c){(void)c;}static void clk_core_disable_lock(struct clk_core*c){(void)c;}
static int rcg_update(struct clk_hw*h,unsigned long rate,unsigned long parent_rate){(void)rate;(void)parent_rate;record('S');updates++;if(!h->core->parent->users){warnings++;return -EBUSY;}return fail_update;}
static int rcg_update_parent(struct clk_hw*h,unsigned long r,unsigned long pr,u8 i){last_index=i;return rcg_update(h,r,pr);}
static const struct clk_ops clk_byte2_ops={.set_rate=rcg_update,.set_rate_and_parent=rcg_update_parent};
static const struct clk_ops clk_pixel_ops={.set_rate=rcg_update,.set_rate_and_parent=rcg_update_parent};
'''
profile_fn='static void profile_init(bool target) { if(target) {\n'+profile+'\n} }\n'
main=r'''
static void reset(void){ntrace=handles=warnings=errors=updates=0;trace[0]=0;fail_get=fail_prepare=fail_update=0;last_index=-1;}
int main(void){
 const unsigned long base=CLK_SET_RATE_PARENT|CLK_GET_RATE_NOCACHE;
 byte_original=(struct clk_init_data){.flags=base,.ops=&clk_byte2_ops};pixel_original=(struct clk_init_data){.flags=base,.ops=&clk_pixel_ops};byte0_clk_src.clkr.hw.init=&byte_original;pclk0_clk_src.clkr.hw.init=&pixel_original;
 profile_init(false);assert(byte0_clk_src.clkr.hw.init==&byte_original&&pclk0_clk_src.clkr.hw.init==&pixel_original);
 profile_init(true);const struct clk_init_data *profiles[]={byte0_clk_src.clkr.hw.init,pclk0_clk_src.clkr.hw.init};
 assert(byte_original.flags==base&&pixel_original.flags==base);
 for(unsigned which=0;which<2;which++){
  assert(profiles[which]->flags==base);
  struct clk_core parent={0};struct clk_hw phw={.core=&parent};parent.hw=&phw;
  struct clk_core child={.flags=profiles[which]->flags};struct clk_hw hw={.core=&child};child.hw=&hw;
  reset();parent.rate_ready=false;struct clk_core*old=__clk_set_parent_before(&child,&parent);__clk_set_parent_after(&child,&parent,old);
  assert(child.parent==&parent&&!parent.users&&!warnings&&!handles&&!updates&&!ntrace);
  // Demonstrate the prior v38 flag's failure under the same zero-rate registration model.
  reset();child.parent=0;child.flags=base|CLK_OPS_PARENT_ENABLE;old=__clk_set_parent_before(&child,&parent);__clk_set_parent_after(&child,&parent,old);assert(warnings==2&&!parent.users);
  child.flags=base;
  for(unsigned active=0;active<2;active++)for(unsigned combined=0;combined<2;combined++){
   reset();parent.rate_ready=true;parent.users=active;
   int ret=combined?profiles[which]->ops->set_rate_and_parent(&hw,140640000,281280000,1):profiles[which]->ops->set_rate(&hw,140640000,281280000);
   assert(!ret&&parent.users==active&&!warnings&&!errors&&!handles&&updates==1&&!strcmp(trace,"GESDP"));if(combined)assert(last_index==1);
  }
  reset();parent.rate_ready=false;parent.users=0;int ret=profiles[which]->ops->set_rate(&hw,1,2);assert(ret==-EINVAL&&errors==1&&!warnings&&!handles&&!updates&&!parent.users&&!strcmp(trace,"GEP"));
  reset();parent.rate_ready=true;fail_prepare=-EIO;ret=profiles[which]->ops->set_rate(&hw,1,2);assert(ret==-EIO&&errors==1&&!warnings&&!handles&&!updates&&!parent.users&&!strcmp(trace,"GEP"));
  reset();fail_get=-ENOMEM;ret=profiles[which]->ops->set_rate(&hw,1,2);assert(ret==-ENOMEM&&errors==1&&!warnings&&!handles&&!updates&&!parent.users);
  reset();child.parent=0;ret=profiles[which]->ops->set_rate(&hw,1,2);assert(ret==-EINVAL&&errors==1&&!warnings&&!handles&&!updates);child.parent=&parent;
  reset();fail_update=-EBUSY;ret=profiles[which]->ops->set_rate(&hw,1,2);assert(ret==-EBUSY&&!warnings&&!handles&&!parent.users&&updates==1&&!strcmp(trace,"GESDP"));
 }
 puts("PASS actual MMCC callbacks and CCF reparent functions: zero-rate registration does not enable/disable PLLs; v38 flag failure reproduced; cold/warm byte/pixel updates and set-rate-and-parent balanced; failed enable/acquire and RCG errors balanced; MSM8994 untouched.");
}
'''
code=prefix+''.join(f'#define {n} {flags[n]}UL\n' for n in ('CLK_SET_RATE_PARENT','CLK_GET_RATE_NOCACHE','CLK_OPS_PARENT_ENABLE'))+wrappers+profile_fn+reparent+main
p=R/'build/validation/scoped-dsi-clock-tests.c';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(code);exe=p.with_suffix('')
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(p),'-o',str(exe)],check=True)
subprocess.run([str(exe)],check=True)
