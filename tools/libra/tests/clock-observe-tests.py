#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute clock probe with writes/votes forbidden, and audit observation DT."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
subprocess.run(['python3', str(workspace / 'scripts/prepare-libra-thermal-observe-dtb.py'), '--clocks'], check=True, stdout=subprocess.DEVNULL)
src = (workspace / 'linux/drivers/clk/qcom/clk-cpu-msm8992.c').read_text()
body = src[src.index('static int msm8992_cluster_probe('):src.index('static unsigned long msm8992_cpu_recalc_rate(')]
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
typedef uintptr_t phys_addr_t;
#define CLK_IS_CRITICAL 1
#define CLK_GET_RATE_NOCACHE 2
#define GFP_KERNEL 0
#define IORESOURCE_MEM 0
#define struct_size(p,m,n) (sizeof(*(p))+sizeof((p)->m[0])*(n))
#define IS_ERR(p) ((uintptr_t)(p)>(uintptr_t)-4096)
#define ERR_PTR(v) ((void*)(intptr_t)(v))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define dev_info(...) ((void)0)
#define dev_err_probe(d,r,...) (r)
struct device {int unused;};struct platform_device {struct device dev;};
struct clk_ops {int unused;};
struct clk_init_data {const char*name;const struct clk_ops*ops;unsigned long flags;const void*parent_hws;unsigned num_parents;};
struct clk_hw {const struct clk_init_data*init;};
struct clk {unsigned long rate;struct clk_hw hw;};
struct resource {phys_addr_t start;};
struct clk_hw_onecell_data {unsigned num;struct clk_hw*hws[];};
struct msm8992_cluster_clk {struct clk_hw hw;void*pll,*mux;unsigned cluster;unsigned long xo_rate;};
struct msm8992_cci_clk {struct clk_hw hw;void*pll;phys_addr_t mux;};
static const struct clk_ops msm8992_cluster_ops={0},msm8992_cci_ops={0},msm8992_cluster_observe_ops={0},msm8992_cci_observe_ops={0};
static bool clusters_probe,clocks_observe=true,clocks_test,cci_test;static unsigned maps,registered,providers;static int fail_map;
static struct clk xo={.rate=19200000},aux={.rate=600000000};static struct resource res={.start=0xf9112000};
static struct clk*devm_clk_get(struct device*d,const char*id){return id[0]=='x'?&xo:&aux;}
static unsigned long clk_get_rate(struct clk*c){return c->rate;}
static struct clk_hw*__clk_get_hw(struct clk*c){return &c->hw;}
static void*devm_kzalloc(struct device*d,unsigned n,int f){return calloc(1,n);}
static int dev_pm_genpd_set_performance_state(struct device*d,unsigned v){assert(!"observation must not vote a supply");return -EIO;}
static void pm_runtime_enable(struct device*d){assert(!"observation must not enable runtime PM");}
static int pm_runtime_resume_and_get(struct device*d){assert(!"observation must not resume a supply");return -EIO;}
static void pm_runtime_put_sync(struct device*d){assert(!"observation must not drop a supply");}
static void pm_runtime_disable(struct device*d){assert(!"observation must not alter runtime PM");}
static void*devm_platform_ioremap_resource(struct platform_device*p,unsigned i){maps++;return fail_map?ERR_PTR(-ENOMEM):(void*)(uintptr_t)(0x1000*(i+1));}
static void*msm8992_map_cluster_mux(struct platform_device*p,unsigned i){maps++;return (void*)(uintptr_t)(0xf900d000+i*0x2000);}
static struct resource*platform_get_resource(struct platform_device*p,int type,unsigned i){assert(i==5);return &res;}
static int devm_clk_hw_register(struct device*d,struct clk_hw*h){assert(h->init->flags==CLK_GET_RATE_NOCACHE);assert(h->init->ops==&msm8992_cluster_observe_ops||h->init->ops==&msm8992_cci_observe_ops||(clocks_test&&h->init->ops==&msm8992_cluster_ops)||(cci_test&&h->init->ops==&msm8992_cci_ops));registered++;return 0;}
static int of_clk_hw_onecell_get;
static int devm_of_clk_add_hw_provider(struct device*d,int getter,struct clk_hw_onecell_data*c){assert(c->num==3);providers++;return 0;}
'''
main = r'''
int main(void){
 struct platform_device p={0};
 assert(msm8992_cluster_probe(&p)==-ENODEV&&!maps&&!registered&&!providers);
 clusters_probe=true;assert(!msm8992_cluster_probe(&p));assert(maps==5&&registered==3&&providers==1);
 clocks_test=true;cci_test=true;assert(!msm8992_cluster_probe(&p));assert(providers==2);
 fail_map=1;assert(msm8992_cluster_probe(&p)==-ENOMEM);assert(providers==2);
 puts("PASS actual observation clock probe: manual gate, read-only ops, no critical enable, no performance/runtime power votes on success or failure");
}
'''
p=workspace/'build/validation/clock-observe-probe.c';p.write_text(prefix+body+main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)
for name in ('msm8992_cluster_observe_ops','msm8992_cci_observe_ops'):
 s=src[src.index('static const struct clk_ops '+name):];s=s[:s.index('};')]
 assert '.recalc_rate' in s and '.set_rate' not in s and '.enable' not in s
variant=workspace/'build/libra-clock-observe.dtb'
def prop(node,key,kind='s'):
 return subprocess.check_output(['fdtget','-t',kind,str(variant),node,key],text=True).strip()
assert prop('/soc/clock-controller@f9015000','status')=='okay'
assert prop('/cpufreq@f9019000','status')=='disabled'
keys=subprocess.check_output(['fdtget','-p',str(variant),'/soc/clock-controller@f9015000'],text=True).splitlines()
assert 'power-domains' not in keys, 'platform attachment must not power a domain before the probe gate'
aux=prop('/clock-controller','phandle','x')
for cpu in (0,1,2,3,0x100,0x101):assert prop(f'/cpus/cpu@{cpu:x}','clocks','x')==aux
print('PASS clock observation DT: CPUs retain auxiliary source, DVFS disabled, implicit platform power-domain writes excluded')
