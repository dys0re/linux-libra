#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise real CPU mux/PLL and fuse decoding code with fake hardware."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
build = workspace / "build/validation"
build.mkdir(parents=True, exist_ok=True)
source = (workspace / "linux/drivers/clk/qcom/clk-cpu-msm8992.c").read_text()
body = source[source.index("#define CPU_MUX"):source.index("static const struct clk_ops msm8992_cluster_ops")]
prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define __iomem
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct clk_hw {int unused;};
static u32 mux[0x100/4], pll[0x100/4];
static bool fail_lock;
static unsigned elapsed, writes;
static void udelay(unsigned us){elapsed+=us;}
static u32 readl(void *p){return *(u32 *)p;}
static void writel(u32 value, void *p){
 if (p >= (void *)pll && p < (void *)(pll+64)) {
   /* Both clusters must use auxiliary clock before PLL0 reconfiguration. */
   assert((mux[0x54/4] & 0x1e)==6);
   if(p==(void *)pll){value&=~BIT(31);if((value&6)==6 && !fail_lock)value|=BIT(31);}
 }
 *(u32 *)p=value;writes++;
}
#define readl_poll_timeout_atomic(addr,val,cond,delay,timeout) \
 ({(val)=readl(addr);(cond)?0:-ETIMEDOUT;})
"""
main = r"""
int main(void){
 struct msm8992_cluster_clk c={.mux=mux,.pll=pll,.xo_rate=19200000};
 const unsigned rates[2][5]={{384000000,460800000,600000000,960000000,1440000000},{384000000,480000000,600000000,1248000000,1824000000}};
 for(c.cluster=0;c.cluster<2;c.cluster++)for(unsigned i=0;i<5;i++){
   /* Start on PLL1 early output; preserve unrelated mux/control bits. */
   memset(pll,0,sizeof pll);mux[0x54/4]=0xa000000a;elapsed=0;
   assert(msm8992_cluster_set_rate(&c.hw,rates[c.cluster][i],600000000)==0);
   assert(msm8992_cluster_recalc_rate(&c.hw,600000000)==rates[c.cluster][i]);
   assert((mux[0x54/4]&~0x1eU)==0xa0000000);
   assert(msm8992_cluster_round_rate(&c.hw,rates[c.cluster][i],0)==rates[c.cluster][i]);
   if(i!=2){assert(pll[PLL_L/4]>=63&&pll[PLL_L/4]<=104);assert(elapsed>=216);assert(pll[PLL_USER/4]&BIT(0));}
 }
 unsigned before=writes;
 assert(msm8992_cluster_set_rate(&c.hw,2000000000,600000000)==-EINVAL&&writes==before);
 fail_lock=true;mux[0x54/4]=0x1a;
 assert(msm8992_cluster_set_rate(&c.hw,384000000,600000000)==-ETIMEDOUT);
 assert(msm8992_cluster_recalc_rate(&c.hw,600000000)==600000000);
 assert((pll[PLL_MODE/4]&7)==0);
 puts("PASS factory low/high-frequency outputs, real mux readback, preservation, VCO range/delay, and lock failure retains auxiliary CPU clock");
}
"""

def run(name, code):
    path = build / (name + ".c")
    path.write_text(code)
    subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", str(path), "-o", str(path.with_suffix(""))], check=True)
    subprocess.run([str(path.with_suffix(""))], check=True)

run("cpu-thermal-clock", prefix + body + main)
source = (workspace / "linux/drivers/thermal/qcom/tsens-8992.c").read_text()
body = source[source.index("static unsigned int msm8992_hw_ids"):source.index("static struct tsens_features msm8992_feat")]
prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define FIELD_GET(mask,val) (((val)&(mask))>>__builtin_ctz(mask))
#define TWO_PT_CALIB 3
#define IS_ERR(p) false
#define PTR_ERR(p) (-ENODEV)
#define kfree free
#define dev_info(...) ((void)0)
struct tsens_priv {int num_sensors;void *dev;};
static u32 primary[3],backup[0x288/4],selector,got[13];
static unsigned computed;
static void *qfprom_read(void*d,const char*name){
 const void *src;size_t bytes;
 if(!strcmp(name,"calib-select")){src=&selector;bytes=4;}
 else if(!strcmp(name,"calib")){src=primary;bytes=sizeof primary;}
 else{assert(!strcmp(name,"calib-backup"));src=backup;bytes=sizeof backup;}
 void *p=malloc(bytes);assert(p);memcpy(p,src,bytes);return p;
}
static void compute_intercept_slope(struct tsens_priv*p,u32*a,u32*b,u32 mode){
 assert(mode==3);for(int i=0;i<13;i++){assert(b[i]-a[i]==270);got[i]=a[i];}computed++;
}
"""
main = r"""
int main(void){
 struct tsens_priv p={.num_sensors=13};
 /* Known primary encoding: base1=400, base2=670, offsets 0..12. */
 primary[0]=400|(670<<10)|(1<<24)|(2<<28);
 for(unsigned i=3;i<11;i++)primary[1]|=i<<((i-3)*4);
 primary[2]=11|(12<<4)|(3<<20);
 assert(!calibrate_8992(&p));for(unsigned i=0;i<13;i++)assert(got[i]==400+i);
 selector=3U<<29;
 /* Backup uses physical IDs and sparse QFPROM rows, not primary indexing. */
 backup[0]=400U<<21;backup[1]=670>>1;
 for(unsigned i=0;i<5;i++)backup[1]|=i<<(9+i*4);
 backup[1]|=5U<<29;backup[3]=(1U<<23)|(6U<<24)|(7U<<28);
 for(unsigned i=8;i<16;i++)backup[(0x440-0x1c0)/4]|=i<<((i-8)*4);
 backup[(0x444-0x1c0)/4]=3;
 assert(!calibrate_8992(&p));
 const unsigned expected[]={0,1,2,3,4,5,7,9,10,11,12,13,14};
 for(unsigned i=0;i<13;i++)assert(got[i]==400+(i==5?13:expected[i]));
 backup[(0x444-0x1c0)/4]=0;assert(calibrate_8992(&p)==-EINVAL&&computed==2);
 selector=0;primary[0]=400|(350<<10);assert(calibrate_8992(&p)==-EINVAL&&computed==2);
 puts("PASS primary/backup fuse decoding, sparse physical IDs, common slope with sensor offsets, uncalibrated/inverted fuses rejected");
}
"""
run("cpu-thermal-calibration", prefix + body + main)

source = (workspace / "linux/drivers/clk/qcom/clk-cpu-msm8992.c").read_text()
definitions = source[source.index("#define CPU_MUX"):source.index("struct msm8992_cluster_clk")]
body = source[source.index("struct msm8992_cci_clk"):source.index("static const struct clk_ops msm8992_cci_ops")]
prefix = r"""
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;typedef uint64_t u64;typedef uintptr_t phys_addr_t;
#define __iomem
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct clk_hw {int unused;};
static u32 mux,pll[64];static bool fail_lock,fail_scm;static unsigned writes,elapsed;
static void udelay(unsigned us){elapsed+=us;}
static u32 readl(void *p){return *(u32 *)p;}
static void writel(u32 v,void*p){
 assert((mux&0x7e)==0x6a); /* safe auxiliary /4 path during reprogramming */
 if(p==(void*)pll){v&=~BIT(31);if((v&6)==6&&!fail_lock)v|=BIT(31);}
 *(u32*)p=v;writes++;
}
static int qcom_scm_io_readl(phys_addr_t addr,u32*v){assert(addr==0xf911211c);if(fail_scm)return -EPERM;*v=mux;return 0;}
static int qcom_scm_io_writel(phys_addr_t addr,u32 v){assert(addr==0xf911211c);if(fail_scm)return -EPERM;mux=v;return 0;}
#define mul_u64_u32_shr(a,b,s) ((u64)(((__uint128_t)(a)*(b))>>(s)))
#define readl_poll_timeout_atomic(addr,val,cond,delay,timeout) \
 ({(val)=readl(addr);(cond)?0:-ETIMEDOUT;})
"""
main = r"""
int main(void){
 struct msm8992_cci_clk c={.pll=pll,.mux=0xf9112000};
 const unsigned long rates[]={134400000,150000000,300000000,384000000,556800000,600000000,729600000,787200000};
 for(unsigned i=0;i<ARRAY_SIZE(rates);i++){
  memset(pll,0,sizeof pll);mux=0x8000001a;elapsed=0;
  assert(!msm8992_cci_set_rate(&c.hw,rates[i],600000000));
  assert(msm8992_cci_recalc_rate(&c.hw,600000000)==rates[i]);assert(mux&0x80000000);
  if(rates[i]!=150000000&&rates[i]!=300000000&&rates[i]!=600000000){assert(pll[PLL_L/4]*19200000UL>=500000000&&pll[PLL_L/4]*19200000UL<=1000000000);assert(elapsed>=25);}
 }
 pll[0x0c/4]=0x80;assert(msm8992_cci_recalc_rate(&c.hw,600000000)==796800000);
 fail_lock=true;assert(msm8992_cci_set_rate(&c.hw,787200000,600000000)==-ETIMEDOUT);
 assert(msm8992_cci_recalc_rate(&c.hw,600000000)==150000000);
 unsigned before=writes;fail_scm=true;assert(msm8992_cci_set_rate(&c.hw,787200000,600000000)==-EPERM&&writes==before);
 puts("PASS actual CCI code: all factory points, secure mux access, VCO/divider range and safe 150MHz fallback, fractional readback, no PLL writes on denied SCM access");
}
"""
run("cpu-thermal-cci", prefix + definitions + body + main)
