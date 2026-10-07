#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise real PCIe clock descriptors and RCG callbacks, including old crash."""
from pathlib import Path
import re
import subprocess

workspace=Path(__file__).resolve().parents[4]
linux=workspace/'linux'
gcc=(linux/'drivers/clk/qcom/gcc-msm8994.c').read_text()
factory=(workspace/'kernel_xiaomi_msm8992/drivers/clk/qcom/clock-gcc-8994.c').read_text()
oem_xo=int(re.search(r'#define\s+gcc_xo_source_val\s+(\d+)',factory)[1])
oem_pipe=int(re.search(r'#define\s+pcie_pipe_source_val\s+(\d+)',factory)[1])
rcg=(linux/'drivers/clk/qcom/clk-rcg2.c').read_text()
common=(linux/'drivers/clk/qcom/common.c').read_text()
def function(src,start):
 i=src.index(start);return src[i:src.index('\n}\n',i)+3]
def declaration(src,start):
 i=src.index(start);return src[i:src.index('\n};',i)+4]
prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <signal.h>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/resource.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1u<<(n))
#define clamp_t(type,v,lo,hi) ((v)<(lo)?(lo):((v)>(hi)?(hi):(v)))
#define do_div(a,b) ((a)/=(b))
#define CLK_SET_RATE_PARENT 1
#define F(f,s,h,m,n) {(f),(s),(2*(h)-1),(m),(n)}
#define CFG_SRC_DIV_SHIFT 0
#define CFG_SRC_SEL_SHIFT 8
#define CFG_SRC_SEL_MASK (7<<8)
#define CFG_MODE_MASK (3<<12)
#define CFG_MODE_DUAL_EDGE (2<<12)
#define CFG_HW_CLK_CTRL_MASK BIT(20)
#define pr_debug(...) ((void)0)
#define RCG_M_OFFSET(r) ((r)->cmd_rcgr+8)
#define RCG_N_OFFSET(r) ((r)->cmd_rcgr+12)
#define RCG_D_OFFSET(r) ((r)->cmd_rcgr+16)
struct clk_parent_data{const char*fw_name,*name;};
struct clk_init_data{const char*name;const struct clk_parent_data*parent_data;unsigned num_parents;const void*ops;};
struct clk_hw{const struct clk_init_data*init;unsigned long rate;};
struct clk_regmap{struct clk_hw hw;void*regmap;};
struct freq_tbl{unsigned long freq;u8 src,pre_div;u16 m,n;};
struct parent_map{u8 src,cfg;};
struct clk_rcg2{u32 cmd_rcgr;u8 mnd_width,hid_width,cfg_off;bool_dummy_not_used;
 const struct parent_map*parent_map;const struct freq_tbl*freq_tbl;struct clk_regmap clkr;int hw_clk_ctrl;};
#define to_clk_rcg2(p) ((struct clk_rcg2*)((char*)(p)-offsetof(struct clk_rcg2,clkr.hw)))
struct clk_rate_request{unsigned long rate,best_parent_rate;struct clk_hw*best_parent_hw;};
enum freq_policy{FLOOR,CEIL};enum{P_XO,P_GPLL0,P_GPLL4,P_PCIE_PIPE};
static int clk_rcg2_ops;
static struct clk_hw parents[2];
static unsigned writes;static u32 offsets[4],values[4];
static unsigned clk_hw_get_num_parents(struct clk_hw*h){return h->init->num_parents;}
static unsigned long clk_hw_get_flags(struct clk_hw*h){return 0;}
static struct clk_hw*clk_hw_get_parent_by_index(struct clk_hw*h,unsigned i){return i<h->init->num_parents?&parents[i]:NULL;}
static unsigned long clk_hw_get_rate(struct clk_hw*h){return h->rate;}
static const struct freq_tbl*qcom_find_freq(const struct freq_tbl*f,unsigned long r){for(;f->freq;f++)if(f->freq>=r)return f;return NULL;}
static const struct freq_tbl*qcom_find_freq_floor(const struct freq_tbl*f,unsigned long r){const struct freq_tbl*best=NULL;for(;f->freq;f++)if(f->freq<=r)best=f;return best;}
static int regmap_update_bits(void*map,u32 off,u32 mask,u32 val){assert(writes<3);offsets[writes]=off;values[writes++]=val&mask;return 0;}
'''.replace('bool_dummy_not_used;','')
code=prefix
for name in ['gcc_xo_map','gcc_pcie_pipe_map']:
 code+=declaration(gcc,'static const struct parent_map '+name+'[]')
for name in ['gcc_xo_pcie0_pipe','gcc_xo_pcie1_pipe']:
 code+=declaration(gcc,'static const struct clk_parent_data '+name+'[]')
for name in ['ftbl_pcie_0_aux_clk_src','ftbl_pcie_1_aux_clk_src','ftbl_pcie_pipe_clk_src']:
 code+=declaration(gcc,'static const struct freq_tbl '+name+'[]')
for name in ['pcie_0_aux_clk_src','pcie_1_aux_clk_src','pcie_0_pipe_clk_src','pcie_1_pipe_clk_src']:
 code+=declaration(gcc,'static struct clk_rcg2 '+name+' =')
code+=function(common,'int qcom_find_src_index(')
code+=function(rcg,'static u8 __clk_rcg2_get_parent(')
code+=function(rcg,'static int _freq_tbl_determine_rate(')
code+=function(rcg,'static int __clk_rcg2_configure(')
code+=r'''
int main(void){
 parents[0].rate=19200000;parents[1].rate=125000000;
 struct clk_rcg2*clocks[]={&pcie_0_aux_clk_src,&pcie_1_aux_clk_src,&pcie_0_pipe_clk_src,&pcie_1_pipe_clk_src};
 for(unsigned i=0;i<4;i++){struct clk_rcg2*r=clocks[i];assert(r->parent_map&&r->clkr.hw.init->num_parents==(i<2?1:2));
 struct clk_rate_request req={.rate=i<2?1011000:125000000};
 struct clk_hw*expected=&parents[i<2?0:1];
 assert(!_freq_tbl_determine_rate(&r->clkr.hw,r->freq_tbl,&req,CEIL));assert(req.best_parent_hw==expected&&req.best_parent_rate==expected->rate);
 writes=0;u32 cfg=0;assert(!__clk_rcg2_configure(r,r->freq_tbl,&cfg));assert(((cfg>>8)&7)==(i<2?OEM_XO:OEM_PIPE)&&(cfg&31)==1);
 if(i<2){assert(writes==3&&values[0]==1&&values[1]==0xed&&values[2]==0xec);assert((cfg&CFG_MODE_MASK)==CFG_MODE_DUAL_EDGE);}
 else{assert(writes==0&&!(cfg&CFG_MODE_MASK));
 assert(__clk_rcg2_get_parent(&r->clkr.hw,OEM_XO<<8)==0);
 assert(__clk_rcg2_get_parent(&r->clkr.hw,cfg)==1); /* reset XO is distinct from PHY125 */
 struct parent_map wrong[]={{P_XO,OEM_XO},{P_PCIE_PIPE,0}};
 const struct parent_map*saved=r->parent_map;r->parent_map=wrong;
 u32 bad=0;assert(!__clk_rcg2_configure(r,r->freq_tbl,&bad));assert(((bad>>8)&7)!=OEM_PIPE);
 r->parent_map=saved;}
 }
 /* Reproduce the prior AUX descriptor: real callback dereferences NULL map. */
 pid_t child=fork();assert(child>=0);
 if(!child){struct rlimit limit={0,0};setrlimit(RLIMIT_CORE,&limit);pcie_0_aux_clk_src.parent_map=NULL;
 struct clk_rate_request req={.rate=1011000};_freq_tbl_determine_rate(&pcie_0_aux_clk_src.clkr.hw,pcie_0_aux_clk_src.freq_tbl,&req,CEIL);_exit(0);}
 int status;assert(waitpid(child,&status,0)==child);assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGSEGV);
 puts("PASS actual GCC PCIe AUX/PIPE descriptors + RCG callbacks: OEM-derived source selections, XO/19 MND, PIPE125 source2 distinct from reset XO; wrong PIPE0 mapping and old NULL AUX map reproduced");
}
'''
code=code.replace('OEM_XO',str(oem_xo)).replace('OEM_PIPE',str(oem_pipe))
target=workspace/'build/validation/pcie-clock.c';target.write_text(code)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-sign-compare',str(target),'-o',str(target.with_suffix(''))],check=True)
subprocess.run([str(target.with_suffix(''))],check=True)
