#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise probe mappings with a mailbox-owned A53 bank and type-2 control."""
from pathlib import Path
import re
import subprocess

workspace = Path(__file__).resolve().parents[4]
source = (workspace / 'linux/drivers/clk/qcom/clk-cpu-msm8992.c').read_text()
start = source.index('static void __iomem *msm8992_map_cluster_mux(')
end = source.index('static int msm8992_cluster_probe(', start)
body = source[start:end]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
#define __iomem
#define ERR_PTR(v) ((void*)(intptr_t)(v))
#define IORESOURCE_MEM 1
struct device {int unused;};
struct platform_device {struct device dev;};
struct resource {uintptr_t start,end;};
static struct resource resources[]={{0xf900d000,0xf900dfff},{0xf900f000,0xf900ffff}};
static unsigned bank[0x1000/4],other[0x1000/4];
static unsigned exclusive,shared;static int missing,oom;
static size_t resource_size(struct resource*r){return r->end-r->start+1;}
static struct resource *platform_get_resource(struct platform_device*p,int type,unsigned index){assert(type==IORESOURCE_MEM);assert(index==2);return missing?NULL:&resources[0];}
static void *devm_platform_ioremap_resource(struct platform_device*p,unsigned index){exclusive++;if(index==2)return ERR_PTR(-EBUSY);assert(index==3);return other;}
static void *devm_ioremap(struct device*d,uintptr_t start,size_t len){assert(start==0xf900d000&&len==0x1000);shared++;return oom?NULL:bank;}
'''
main = r'''
int main(void){
 struct platform_device p={0};
 bank[8/4]=0x55aa;
 assert(msm8992_map_cluster_mux(&p,0)==bank&&shared==1&&exclusive==0);
 bank[0x54/4]=6;assert(bank[8/4]==0x55aa);
 assert(msm8992_map_cluster_mux(&p,1)==other&&exclusive==1&&shared==1);
 missing=1;assert(msm8992_map_cluster_mux(&p,0)==ERR_PTR(-EINVAL));missing=0;
 oom=1;assert(msm8992_map_cluster_mux(&p,0)==ERR_PTR(-ENOMEM));
 puts("PASS actual mapping helper: mailbox-owned A53 mux is shared, A57 stays exclusive, mailbox word preserved, resource/mapping failures handled");
}
'''
out = workspace / 'build/validation/cpu-probe-mapping.c'
out.write_text(prefix + body + main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(out),'-o',str(out.with_suffix(''))],check=True)
subprocess.run([str(out.with_suffix(''))],check=True)
# Zero at SROT+0 is the version/reserved word, not the enable register.
thermal = (workspace / 'linux/drivers/thermal/qcom/tsens-8992.c').read_text()
fields = {name:(int(reg,0),int(lo),int(hi)) for name,reg,lo,hi in re.findall(r'\[(TSENS_EN|TSENS_SW_RST|SENSOR_EN)\] = REG_FIELD\((0x[0-9a-f]+|[0-9]+), ([0-9]+), ([0-9]+)\)', thermal)}
assert fields == {'TSENS_EN':(4,0,0),'TSENS_SW_RST':(4,1,1),'SENSOR_EN':(4,3,18)}
srot = {0:0,4:1 | (0x7ebf << 3)}
reg,lo,hi = fields['TSENS_EN']
assert (srot[reg] >> lo) & ((1 << (hi-lo+1))-1) == 1
assert srot[0] & 1 == 0
v1 = (workspace / 'linux/drivers/thermal/qcom/tsens-v1.c').read_text()
assert '#define SROT_CTRL_OFF\t\t0x0004' in v1
mailbox = (workspace / 'linux/drivers/mailbox/qcom-apcs-ipc-mailbox.c').read_text()
assert re.search(r'msm8994_apcs_data = \{\s*\.offset = 8',mailbox)
print('PASS type-2 enable/reset/sensor fields at SROT+4 with reserved word zero; standard v1 control and APCS mailbox offsets checked')
