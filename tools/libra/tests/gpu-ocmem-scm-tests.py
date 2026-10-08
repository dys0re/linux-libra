#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute OCMEM SCM descriptors and allocation failure cleanup."""
from pathlib import Path
import subprocess
import tempfile

W = Path(__file__).resolve().parents[4]
scm = (W/'linux/drivers/firmware/qcom/qcom_scm.c').read_text()
ocmem = (W/'linux/drivers/soc/qcom/ocmem.c').read_text()


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start)+3]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
typedef uint32_t u32;
enum qcom_scm_ocmem_client {QCOM_SCM_OCMEM_GRAPHICS_ID=1};
#define ARM_SMCCC_OWNER_SIP 2
#define QCOM_SCM_SVC_OCMEM 15
#define QCOM_SCM_OCMEM_LOCK_CMD 1
#define QCOM_SCM_OCMEM_UNLOCK_CMD 2
#define QCOM_SCM_ARGS(n) (n)
struct qcom_scm_desc {unsigned svc,cmd,owner,arginfo;uint64_t args[4];};
struct scm_device {void*dev;} scm_instance;
static struct scm_device *__scm=&scm_instance;
static int firmware_error,calls;
static int qcom_scm_call(void*dev,const struct qcom_scm_desc*d,void*res) {
 (void)dev;(void)res;calls++;
 /* OEM SCM_SIP_FNID(0x0f, 1/2), not the architectural owner 0. */
 assert(((d->owner<<24)|(d->svc<<8)|d->cmd)==(0x02000f00|d->cmd));
 assert(d->cmd==1||d->cmd==2);
 assert(d->arginfo==(d->cmd==1?4:3));
 assert(d->args[0]==1&&d->args[1]==0&&d->args[2]==0x80000);
 if(d->cmd==1)assert(d->args[3]==0);
 return firmware_error;
}
enum ocmem_client {OCMEM_GRAPHICS};
enum ocmem_macro_state {CORE_ON=2,CLK_OFF=4};
enum region_mode {WIDE_MODE=0,MODE_DEFAULT=0};
struct ocmem {void*dev;unsigned long active_allocations;};
struct ocmem_buf {unsigned long offset,addr,len;};
#define OCMEM_MIN_ALLOC 65536
#define OCMEM_MIN_ALIGN 65536
#define OCMEM_REG_GFX_MPU_START 0x1004
#define OCMEM_REG_GFX_MPU_END 0x1008
#define BIT(n) (1UL<<(n))
#define IS_ALIGNED(n,a) (!((n)&((a)-1)))
#define WARN_ON(n) (n)
#define GFP_KERNEL 0
#define kzalloc(n,flags) calloc(1,n)
#define __free(n) __attribute__((cleanup(n)))
static void kfree(struct ocmem_buf**p){free(*p);}
#define return_ptr(p) do {struct ocmem_buf *result=(p);(p)=NULL;return result;}while(0)
#define ERR_PTR(n) ((void*)(intptr_t)(n))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
static bool test_and_set_bit_lock(unsigned bit,unsigned long*v){bool old=*v&BIT(bit);*v|=BIT(bit);return old;}
static void clear_bit_unlock(unsigned bit,unsigned long*v){*v&=~BIT(bit);}
static unsigned long device_address(struct ocmem*o,enum ocmem_client c,unsigned long offset){(void)o;(void)c;return offset;}
static int range_calls,last_state;
static void update_range(struct ocmem*o,struct ocmem_buf*b,enum ocmem_macro_state state,enum region_mode mode){(void)o;assert(b->len==0x80000&&mode==0);range_calls++;last_state=state;}
static bool qcom_scm_ocmem_lock_available(void){return true;}
static void ocmem_write(struct ocmem*o,unsigned reg,unsigned val){(void)o;(void)reg;(void)val;abort();}
#define dev_err(...) do {}while(0)
#define dev_dbg(...) do {}while(0)
'''
main = r'''
int main(void) {
 struct ocmem o={0};struct ocmem_buf*b;
 assert(!qcom_scm_ocmem_lock(1,0,0x80000,0));
 assert(!qcom_scm_ocmem_unlock(1,0,0x80000));
 firmware_error=-EIO;
 assert(qcom_scm_ocmem_lock(1,0,0x80000,0)==-EIO);
 assert(qcom_scm_ocmem_unlock(1,0,0x80000)==-EIO);
 assert(IS_ERR(ocmem_allocate(&o,OCMEM_GRAPHICS,0x80000)));
 assert(!o.active_allocations&&range_calls==2&&last_state==CLK_OFF);
 firmware_error=0;
 b=ocmem_allocate(&o,OCMEM_GRAPHICS,0x80000);
 assert(!IS_ERR(b)&&o.active_allocations&&b->addr==0&&b->len==0x80000);
 assert(range_calls==3&&last_state==CORE_ON);
 assert(IS_ERR(ocmem_allocate(&o,OCMEM_GRAPHICS,0x80000)));
 free(b);assert(calls==6);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp)/'scm.c',Path(tmp)/'scm'
    c.write_text(prefix + function(scm,'int qcom_scm_ocmem_lock(')
                 + function(scm,'int qcom_scm_ocmem_unlock(')
                 + function(ocmem,'struct ocmem_buf *ocmem_allocate(') + main)
    subprocess.run(['cc','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
config=(W/'build/libra/.config').read_text().splitlines()
for name in ('PM_DEVFREQ','DEVFREQ_GOV_SIMPLE_ONDEMAND','DEVFREQ_THERMAL'):
    assert 'CONFIG_'+name+'=y' in config
assert (W/'cfg/msm8992-libra.config').read_bytes()==(W/'linux/tools/libra/cfg/msm8992-libra.config').read_bytes()
print('PASS actual OCMEM lock/unlock use OEM SIP owner, graphics ID/size/mode; rejected allocation powers macros off and frees ownership; GPU devfreq/cooling enabled')
