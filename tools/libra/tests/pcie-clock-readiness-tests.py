#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute deferred AUX/PIPE validation without accepting halted clocks."""
from pathlib import Path
import re
import subprocess

workspace=Path(__file__).resolve().parents[4]
source=(workspace/'linux/drivers/pci/controller/dwc/pcie-qcom.c').read_text()
start=source.index('static int qcom_pcie_link_clocks_ready_msm8992(')
body=source[start:source.index('\n}\n',start)+3]
prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
typedef unsigned int u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1u<<(n))
#define dev_err(...) ((void)0)
struct regmap{int unused;};struct dev{int unused;};struct pci{struct dev*dev;};
struct qcom_pcie{struct pci*pci;union{struct{struct regmap*gcc;}msm8992;}res;};
static u32 aux,pipe;static int snapshots,reads;
static void qcom_pcie_snapshot_msm8992(struct qcom_pcie*p,const char*s){snapshots++;}
#define regmap_read_poll_timeout(map,reg,val,cond,delay,timeout) ({assert(map&&delay==10&&timeout==100000);assert(reg==0x1ad4||reg==0x1ad8);reads++;val=reg==0x1ad4?aux:pipe;(cond)?0:-ETIMEDOUT;})
'''
main=r'''
int main(void){struct regmap map;struct pci pci={0};struct qcom_pcie p={.pci=&pci,.res.msm8992.gcc=&map};
 aux=pipe=1;assert(!qcom_pcie_link_clocks_ready_msm8992(&p)&&reads==2&&snapshots==1);
 for(int i=0;i<2;i++){aux=pipe=1;reads=snapshots=0;if(!i)aux=0x80000001;else pipe=0x80000001;
 assert(qcom_pcie_link_clocks_ready_msm8992(&p)==-ETIMEDOUT&&snapshots==1&&reads==i+1);}
 aux=0;pipe=1;assert(qcom_pcie_link_clocks_ready_msm8992(&p)==-ETIMEDOUT); /* no enable request */
 p.res.msm8992.gcc=0;assert(qcom_pcie_link_clocks_ready_msm8992(&p)==-ENODEV);
 puts("PASS actual link-stage clock check: AUX/PIPE require enable+running bits, halted/unrequested clocks fail with bounded timeout; absent map fails");}
'''
p=workspace/'build/validation/pcie-clock-readiness.c';p.write_text(prefix+body+main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-sign-compare',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)
gcc=(workspace/'linux/drivers/clk/qcom/gcc-msm8994.c').read_text()
probe=gcc[gcc.index('static int gcc_msm8994_probe('):gcc.index('static struct platform_driver gcc_msm8994_driver')]
assert probe.index('of_device_is_compatible')<probe.index('gcc_pcie_0_aux_clk.halt_check = BRANCH_HALT_DELAY;')
link=source[source.index('static int qcom_pcie_start_link('):source.index('static void qcom_pcie_clear_aspm_l0s(')]
assert link.index('ltssm_enable(pcie)')<link.index('link_clocks_ready(pcie)')
print('PASS delay policy scoped to MSM8992 AUX only; hardware-running validation follows LTSSM activation')

# Replay the selected LTSSM callback against separate PARF/ELBI banks, deriving
# the expected write from the unmodified factory driver rather than our code.
factory=(workspace/'kernel_xiaomi_msm8992/drivers/pci/host/pci-msm.c').read_text()
oem_offset=int(re.search(r'#define\s+PCIE20_PARF_LTSSM\s+(0x[0-9a-fA-F]+)',factory)[1],16)
oem_bit=int(re.search(r'msm_pcie_write_mask\(dev->parf \+ PCIE20_PARF_LTSSM, 0, BIT\((\d+)\)\)',factory)[1])
oem_mrrs=int(re.search(r'#define\s+PCIE_TLP_RD_SIZE\s+(0x[0-9a-fA-F]+)',factory)[1],16)
ops=source[source.index('static const struct qcom_pcie_ops ops_msm8992 = {'):]
callback=re.search(r'\.ltssm_enable\s*=\s*(\w+)',ops)[1]
def extract(name,kind='void'):
    start=source.index('static '+kind+' '+name+'(')
    return source[start:source.index('\n}\n',start)+3]
constants='\n'.join(re.search(r'^#define\s+'+n+r'\s+.*$',source,re.M)[0]
                    for n in ('PARF_LTSSM','LTSSM_EN','ELBI_SYS_CTRL','ELBI_SYS_CTRL_LT_ENABLE','PARF_AXI_MSTR_WR_ADDR_HALT'))
prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;typedef uint16_t u16;
#define BIT(n) (1u<<(n))
#define PCI_CAP_ID_EXP 0x10
#define PCI_EXP_DEVCTL 8
#define PCI_EXP_DEVCTL_READRQ 0x7000
#define PCI_EXP_DEVCTL_READRQ_4096B 0x5000
#define PCIE_PORT_AFR 0x70c
#define dev_info(...) ((void)0)
struct dw_pcie{void*dbi_base;int linked;};
struct qcom_pcie { void *parf, *elbi;struct dw_pcie*pci; };
static struct qcom_pcie*live;static int mrrs_written,hpc;
static u32 readl(void *p) { return *(u32*)p; }
static void writel(u32 v, void *p) {
 if(p==live->parf+0x1b0) assert(mrrs_written&&((*(u16*)(live->pci->dbi_base+0x78)>>12)&7)==OEM_MRRS);
 *(u32*)p=v; }
static u16 dw_pcie_find_capability(struct dw_pcie*p,int id){assert(id==PCI_CAP_ID_EXP);return 0x70;}
static u16 dw_pcie_readw_dbi(struct dw_pcie*p,int r){assert(r==0x78);return *(u16*)(p->dbi_base+r);}
static void dw_pcie_writew_dbi(struct dw_pcie*p,int r,u16 v){assert(r==0x78);mrrs_written=1;*(u16*)(p->dbi_base+r)=v;}
static int dw_pcie_link_up(struct dw_pcie*p){return p->linked;}
static void qcom_pcie_clear_hpc(struct dw_pcie*p){hpc++;}
static void qcom_pcie_snapshot_msm8992(struct qcom_pcie*p,const char*s){}
'''
main=r'''
int main(void) {
 u32 parf[512]={0},elbi[64]={0},dbi[1024]={0};
 struct dw_pcie pci={.dbi_base=dbi};
 struct qcom_pcie p={.parf=parf,.elbi=elbi,.pci=&pci};live=&p;
 dbi[0x78/4]=0x00102810;
 dbi[0x70c/4]=0x1b2c2c00;
 assert(!qcom_pcie_post_init_msm8992(&p));
 assert(dbi[0x70c/4]==0x1b2c2c00&&hpc==1);
 memset(parf,0,sizeof(parf));
 parf[OEM_OFFSET/4]=0x10a00000;
 SELECTED(&p);
 assert(dbi[0x78/4]==0x00105810); /* status and other DevCtl bits unchanged */
 assert(parf[OEM_OFFSET/4]==(0x10a00000|BIT(OEM_BIT)));
 for(unsigned i=0;i<512;i++) if(i!=OEM_OFFSET/4) assert(!parf[i]);
 for(unsigned i=0;i<64;i++) assert(!elbi[i]);
 SELECTED(&p); assert(parf[OEM_OFFSET/4]==(0x10a00000|BIT(OEM_BIT)));
 memset(parf,0,sizeof(parf));
 qcom_pcie_2_1_0_ltssm_enable(&p);
 assert(!parf[OEM_OFFSET/4]); assert(elbi[1]==1);
 qcom_pcie_host_post_init_msm8992(&p);assert(dbi[0x70c/4]==0x1b2c2c00);
 pci.linked=1;qcom_pcie_host_post_init_msm8992(&p);assert(dbi[0x70c/4]==0x1b2cac00);
 puts("PASS actual MSM8992 LTSSM callback matches OEM PARF offset/bit, preserves other bits, leaves ELBI untouched; old callback does not start PARF training");
}
'''
p=workspace/'build/validation/pcie-ltssm.c'
p.write_text((prefix+constants+'\n'+extract('qcom_pcie_2_3_2_ltssm_enable')+'\n'+extract(callback)+'\n'+extract('qcom_pcie_2_1_0_ltssm_enable')+
              '\n'+extract('qcom_pcie_post_init_msm8992','int')+'\n'+extract('qcom_pcie_host_post_init_msm8992')+main)
             .replace('OEM_OFFSET',str(oem_offset)).replace('OEM_BIT',str(oem_bit)).replace('SELECTED',callback).replace('OEM_MRRS',str(oem_mrrs)))
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)
print('PASS OEM MRRS before LTSSM; N_FTS unchanged before/unlinked training and configured only after link-up; word write preserves DevStatus')
