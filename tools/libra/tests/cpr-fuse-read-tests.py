#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the fuse reader against a provider that rejects unrelated rows."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
src = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
start = src.index('static int msm8992_read_cpr_fuses(')
reader = src[start:src.index('\n}\n', start) + 3]
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define IS_ERR(p) ((intptr_t)(p)<0 && (intptr_t)(p)>-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define kfree free
#define dev_info(...) ((void)0)
struct device {int unused;}; struct nvmem_cell {unsigned row;};
static struct nvmem_cell cell;
static unsigned reads, seen[16];
static bool backup;
static int fail_row=-1;
static unsigned long msm8992_fuse_bits(const u8*d,unsigned row,unsigned bit,unsigned width){
 unsigned long v=0;for(unsigned i=0;i<width;i++)v|=(unsigned long)((d[(row*64+bit+i)/8]>>((bit+i)%8))&1)<<i;return v;
}
static struct nvmem_cell* devm_nvmem_cell_get(struct device*d,const char*name){
 (void)d;unsigned row;assert(sscanf(name,"cpr-row%u",&row)==1);
 switch(row){case 22:case 56:case 57:case 62:case 136:case 137:case 138:case 139:case 140:break;default:assert(0);}
 cell.row=row;return &cell;
}
static u8* nvmem_cell_read(struct nvmem_cell*c,size_t*len){
 assert(reads<16);seen[reads++]=c->row;
 if((int)c->row==fail_row)return (u8*)(intptr_t)-EIO;
 u8*v=calloc(8,1);*len=8;if(c->row==62&&backup)v[6]=1;return v;
}
'''
main = r'''
int main(void){struct device dev={0};u8 data[0x500]={0};
 const unsigned primary[]={62,137,22,138,139,140},redundant[]={62,137,22,56,57,136};
 assert(!msm8992_read_cpr_fuses(&dev,data));assert(reads==6&&!memcmp(seen,primary,sizeof(primary)));
 backup=true;reads=0;memset(data,0,sizeof(data));assert(!msm8992_read_cpr_fuses(&dev,data));
 assert(reads==6&&!memcmp(seen,redundant,sizeof(redundant)));
 fail_row=137;reads=0;assert(msm8992_read_cpr_fuses(&dev,data)==-EIO&&reads==2);
 puts("PASS real CPR reader: selector first, only factory-used 8-byte rows, unused bank skipped, provider errors stop reads; no whole-bank sweep");}
'''
target = workspace / 'build/validation/cpr-fuse-read.c'
target.write_text(prefix + reader + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
