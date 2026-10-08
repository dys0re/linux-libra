#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute OEM pool initialization and pre-domain context-fault handling."""
from pathlib import Path
import re
import subprocess
import tempfile

W = Path(__file__).resolve().parents[4]
s = (W / 'linux/drivers/iommu/arm/arm-smmu/qcom_iommu.c').read_text()


def fn(name):
    start = s.rfind('\nstatic ', 0, s.index(name + '(')) + 1
    return s[start:s.index('\n}\n', start) + 3]


prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <errno.h>
#define SZ_1M (1024*1024)
#define GFP_KERNEL 0
#define DMA_ATTR_NO_KERNEL_MAPPING 1
typedef unsigned long dma_addr_t;
struct device {int x;};
#define dev_info(...) do {} while(0)
#define dev_err(...) do {} while(0)
#define dev_err_probe(dev,ret,...) (ret)
static int fail,cp_calls,size_calls,alloc_calls,init_calls,free_calls;
static int qcom_scm_iommu_set_cp_pool_size(unsigned spare,unsigned size) { assert(!spare&&size==300*SZ_1M);cp_calls++;return fail==1?-EIO:0; }
static int qcom_scm_iommu_secure_ptbl_size(unsigned spare,size_t *size) { assert(!spare);size_calls++;*size=151552;return fail==2?-EIO:0; }
static void *dma_alloc_attrs(struct device*d,size_t size,dma_addr_t *addr,int flags,unsigned long attrs) { (void)d;(void)flags; assert(size==151552&&attrs==1);alloc_calls++;*addr=0xd5000000;return fail==3?NULL:(void*)1; }
static int qcom_scm_iommu_secure_ptbl_init(dma_addr_t addr,size_t size,unsigned spare) { assert(addr==0xd5000000&&size==151552&&!spare);init_calls++;return fail==4?-EIO:0; }
static void dma_free_attrs(struct device*d,size_t size,void*addr,dma_addr_t pa,unsigned long attrs) { (void)d;assert(size==151552&&addr==(void*)1&&pa==0xd5000000&&attrs==1);free_calls++; }
typedef unsigned u32;
typedef uint64_t u64;
typedef int irqreturn_t;
#define IRQ_NONE 0
#define IRQ_HANDLED 1
#define ARM_SMMU_CB_FSR 1
#define ARM_SMMU_CB_FSYNR0 2
#define ARM_SMMU_CB_FAR 3
#define ARM_SMMU_CB_RESUME 4
#define ARM_SMMU_CB_FSR_FAULT 1
#define ARM_SMMU_RESUME_TERMINATE 1
static void test_log(struct device*d,const char*fmt,...) { (void)d;(void)fmt; }
#define dev_err_ratelimited(...) test_log(__VA_ARGS__)
struct qcom_iommu_ctx {void*domain;struct device*dev;unsigned asid;};
static int fault_status,reports,writes;
static unsigned iommu_readl(struct qcom_iommu_ctx*c,int reg) { (void)c;return reg==1?fault_status:0; }
static uint64_t iommu_readq(struct qcom_iommu_ctx*c,int reg) { (void)c;assert(reg==3);return 0x100000; }
static int report_iommu_fault(void*d,struct device*dev,uint64_t addr,int flags) { (void)dev;(void)flags;assert(d&&addr==0x100000);reports++;return 1; }
static void iommu_writel(struct qcom_iommu_ctx*c,int reg,unsigned val) { (void)c;assert((reg==1||reg==4)&&val==1);writes++; }
'''
main = r'''
int main(int argc,char**argv) {
 struct device d={0};struct qcom_iommu_ctx c={.dev=&d};bool board=argc==1;
 (void)argv;
 for(fail=1;fail<=4;fail++){assert(qcom_iommu_sec_ptbl_init(&d,true)<0);}
 assert(cp_calls==4&&size_calls==3&&alloc_calls==2&&init_calls==1&&free_calls==1);
 fail=0;assert(!qcom_iommu_sec_ptbl_init(&d,board));assert(cp_calls==(board?5:4));
 assert(size_calls==4&&alloc_calls==3&&init_calls==2);assert(!qcom_iommu_sec_ptbl_init(&d,true));assert(size_calls==4&&alloc_calls==3&&init_calls==2);
 assert(qcom_iommu_fault(0,&c)==IRQ_NONE && !reports && !writes);
 fault_status=1;assert(qcom_iommu_fault(0,&c)==IRQ_HANDLED && !reports && writes==2);
 c.domain=(void*)1;assert(qcom_iommu_fault(0,&c)==IRQ_HANDLED && reports==1 && writes==4);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp) / 'init.c', Path(tmp) / 'init'
    c.write_text(prefix + fn('qcom_iommu_sec_ptbl_init') + fn('qcom_iommu_fault') + main)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
    subprocess.run([str(exe), 'other-soc'], check=True)
print('PASS actual pool/fault callbacks: OEM 300MiB virtual limit, 148KiB real pool, one allocation, all failures released, no NULL-domain fault callback')

probe = fn('qcom_iommu_device_probe')
assert 'msm8992 || qcom_iommu_has_secure_context' in probe
assert probe.index('qcom_iommu_sec_ptbl_init(') < probe.index('pm_runtime_resume_and_get(')
domain = fn('qcom_iommu_init_domain')
assert domain.index('ctx->domain = domain;', domain.index('/* SCTLR */')) < domain.index('qcom_iommu_program_context(')
hw = (W / 'kernel_xiaomi_msm8992/drivers/iommu/msm_iommu_hw-v1.h').read_text()
shifts = [int(re.search('CB_ACTLR_'+name+r'_SHIFT\s+(\d+)', hw)[1]) for name in ('BPRCOSH','BPRCISH','BPRCNSH')]
assert shifts == [28,29,30]
assert 'BIT(28) | BIT(29) | BIT(30)' in s
assert s.count('ARM_SMMU_CB_ACTLR, MSM8992_ACTLR_BPRC') == 1
print('PASS OEM L2 routing configured/restored and IRQ domain published before context enable')

# Execute the real context writer with a QSMMUv1 register map. A read or
# write at +0x10 reproduces the invalid v2 access found in the #85 panic.
context_prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((~0U >> (31-(h))) & (~0U << (l)))
#define FIELD_PREP(mask,val) (((val) << __builtin_ctz(mask)) & (mask))
#define ARM_SMMU_TCR_EAE BIT(31)
#define ARM_SMMU_CB_SCTLR 0x00
#define ARM_SMMU_CB_ACTLR 0x04
#define ARM_SMMU_CB_TCR2 0x10
#define ARM_SMMU_CB_TTBR0 0x20
#define ARM_SMMU_CB_TTBR1 0x28
#define ARM_SMMU_CB_TCR 0x30
#define ARM_SMMU_CB_S1_MAIR0 0x38
#define ARM_SMMU_CB_S1_MAIR1 0x3c
#define ARM_SMMU_CB_FSR 0x58
#define ARM_SMMU_CB_FAR 0x60
#define ARM_SMMU_CB_FSR_FAULT 0xc00001fe
#define MSM8992_ACTLR_BPRC (BIT(28)|BIT(29)|BIT(30))
struct io_pgtable_cfg {
 unsigned ias;
 struct {struct {unsigned irgn,orgn,sh;} tcr;} arm_lpae_s1_cfg;
};
struct qcom_iommu_ctx {void *domain;u64 ttbr0;u32 tcr,tcr2,mair0,mair1,sctlr;};
static u64 regs[256];
static unsigned trace[64],n,barriers;
static bool v1;
static void iommu_writel(struct qcom_iommu_ctx*c,unsigned reg,u32 val) {
 assert(!(v1&&reg==0x10)); assert(reg<0x400);
 if(reg==0&&!val){n=barriers=0;}
 if(reg==0&&val){assert(c->domain&&barriers);}
 trace[n++]=reg;regs[reg/4]=val;
}
static void iommu_writeq(struct qcom_iommu_ctx*c,unsigned reg,u64 val) {
 (void)c;assert(reg==0x20||reg==0x28);
 assert(regs[0x30/4]&BIT(31));trace[n++]=reg;regs[reg/4]=val;
}
#define wmb() (++barriers)
'''
context_main = r'''
int main(void) {
 struct io_pgtable_cfg cfg={.ias=32,.arm_lpae_s1_cfg.tcr={.irgn=0,.orgn=1,.sh=2}};
 struct qcom_iommu_ctx ctx={.domain=(void*)1,.ttbr0=0x00030000d5100000ULL,
   .tcr2=0x38001,.mair0=0xff44,.mair1=0,.sctlr=0x10e7};
 ctx.tcr=qcom_iommu_msm8992_tcr(&cfg);
 assert(ctx.tcr==0x80002420);
 cfg.ias=30;assert((qcom_iommu_msm8992_tcr(&cfg)&7)==2);
 cfg.ias=32;cfg.arm_lpae_s1_cfg.tcr.irgn=1;
 cfg.arm_lpae_s1_cfg.tcr.sh=3;
 assert(qcom_iommu_msm8992_tcr(&cfg)==0x80003520);
 for(unsigned pass=0;pass<2;pass++) {
   v1=true;qcom_iommu_program_context(&ctx,true);
   assert(n==10&&barriers==2&&trace[0]==0&&trace[1]==4);
   assert(trace[4]==0x30&&trace[5]==0x20&&trace[6]==0x28);
   assert(trace[9]==0&&regs[0]==0x10e7&&regs[4/4]==0x70000000);
   assert(regs[0x20/4]==ctx.ttbr0);
 }
 v1=false;regs[4/4]=0;qcom_iommu_program_context(&ctx,false);
 assert(n==10&&trace[3]==0x10&&regs[0x10/4]==ctx.tcr2&&!regs[4/4]);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'context.c', Path(tmp)/'context'
    c.write_text(context_prefix + fn('qcom_iommu_msm8992_tcr') + fn('qcom_iommu_program_context') + context_main)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
resume = fn('qcom_iommu_resume')
assert 'qcom_iommu_program_context(ctx, true)' in resume
assert 'ARM_SMMU_CB_TCR2' not in domain and 'ARM_SMMU_CB_TCR2' not in resume
assert 'iommu_read' not in domain
for name, expected in [('EPD1',5),('T0SZ',0),('IRGN0',8),('ORGN0',10),('SH0',12)]:
    assert int(re.search('CB_TTBCR_'+name+r'_SHIFT\s+(\d+)',hw)[1]) == expected
print('PASS actual context writer: QSMMUv1 attach/resume avoid reserved TCR2, OEM TTBCR bits, TCR before TTBR, IRQ enable last; v2 TCR2 retained')
