#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise GEM placement and automatic GPU-provider startup ordering."""
from pathlib import Path
import os
import subprocess
import tempfile

W=Path(__file__).resolve().parents[4]
gem=(W/'linux/drivers/gpu/drm/msm/msm_gem.c').read_text()
start=gem.index('struct drm_gem_object *msm_gem_new(')
decision=gem[start:gem.index('\n\tif (GEM_WARN_ON(',start)]
decision=decision.replace('struct drm_gem_object *msm_gem_new(', 'static bool choose_vram(')
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uint32_t uint32_t;
#define MSM_BO_STOLEN 1
#define MSM_BO_SCANOUT 2
#define PAGE_ALIGN(x) (((x)+4095)&~4095)
struct device {bool mapped;};
struct platform_device {struct device dev;};
struct msm_drm_private {struct platform_device*gpu_pdev;struct {unsigned size;} vram;};
struct drm_device {void*dev_private;bool display_mmu;};
static bool msm_use_mmu(struct drm_device*d){return d->display_mmu;}
static bool device_iommu_mapped(struct device*d){return d->mapped;}
'''
main=r'''
int main(void) {
 struct platform_device gpu={.dev.mapped=true};
 struct msm_drm_private p={.vram.size=32<<20};
 struct drm_device d={.dev_private=&p};
 assert(choose_vram(&d,64<<20,0));
 p.gpu_pdev=&gpu;
 assert(!choose_vram(&d,64<<20,0));
 assert(choose_vram(&d,8<<20,MSM_BO_SCANOUT));
 assert(choose_vram(&d,8<<20,MSM_BO_STOLEN));
 gpu.dev.mapped=false;assert(choose_vram(&d,64<<20,0));
 d.display_mmu=true;assert(!choose_vram(&d,64<<20,0));
 assert(choose_vram(&d,8<<20,MSM_BO_SCANOUT));
 p.vram.size=0;assert(!choose_vram(&d,8<<20,MSM_BO_SCANOUT));
 return 0;
}
'''
with tempfile.TemporaryDirectory() as td:
    c,exe=Path(td)/'gem.c',Path(td)/'gem'
    c.write_text(prefix+decision+'\n return use_vram;\n}\n'+main)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-but-set-parameter',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS real GEM allocation decision: GPU textures use pages beyond 32MiB, scanout/stolen stay contiguous, legacy display/import policy unchanged')

start=gem.index('static struct msm_gem_vma *get_vma_locked(')
vma_fn=gem[start:gem.index('\n}\n',start)+3]
vma_prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <errno.h>
typedef uint64_t u64;
struct drm_gem_object {unsigned size;};
struct msm_gem_address_space {int x;};
struct msm_gem_vma {u64 iova;};
static struct msm_gem_vma fixture={.iova=0x1000};
static int existing,adds,warnings;
#define msm_gem_assert_locked(obj) ((void)(obj))
#define GEM_WARN_ON(x) ((x)?(++warnings,1):0)
#define ERR_PTR(x) ((void*)(intptr_t)(x))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
static struct msm_gem_vma *lookup_vma(struct drm_gem_object*o,struct msm_gem_address_space*a){(void)o;(void)a;return existing?&fixture:0;}
static struct msm_gem_vma *add_vma(struct drm_gem_object*o,struct msm_gem_address_space*a){(void)o;assert(a);adds++;return &fixture;}
static int msm_gem_vma_init(struct msm_gem_vma*v,unsigned size,u64 lo,u64 hi){(void)v;(void)size;(void)lo;(void)hi;return 0;}
static void del_vma(struct msm_gem_vma*v){(void)v;}
'''
with tempfile.TemporaryDirectory() as td:
    c,exe=Path(td)/'vma.c',Path(td)/'vma'
    c.write_text(vma_prefix+vma_fn+r'''
int main(void){struct drm_gem_object o={.size=4096};struct msm_gem_address_space a={0};
 assert(get_vma_locked(&o,0,0,UINT64_MAX)==ERR_PTR(-EINVAL));
 assert(!adds&&!warnings);assert(get_vma_locked(&o,&a,0,UINT64_MAX)==&fixture);
 existing=1;assert(get_vma_locked(&o,0,0,UINT64_MAX)==&fixture);
 assert(adds==1&&!warnings);return 0;}
''')
    subprocess.run(['cc','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS real VMA lookup rejects page-backed physical scanout without warning; GPU mappings and contiguous scanout still work')

dsi=(W/'linux/drivers/gpu/drm/msm/dsi/dsi_host.c').read_text()
start=dsi.index('int dsi_tx_buf_alloc_6g(')
allocator=dsi[start:dsi.index('\n}\n',start)+3]
dma_prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;typedef uint8_t u8;
#define MSM_BO_WC 2
#define MSM_BO_STOLEN 0x10000000
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
struct drm_gem_object {unsigned size;};
struct msm_gem_address_space {int x;};
struct msm_kms {struct msm_gem_address_space*aspace;};
struct msm_drm_private {struct msm_kms*kms;};
struct drm_device {void*dev_private;};
struct msm_dsi_host {struct drm_device*dev;struct msm_gem_address_space*aspace;struct drm_gem_object*tx_gem_obj;uint64_t tx_iova;unsigned tx_size;};
static bool fail;static struct drm_gem_object bo={.size=4096};
static struct msm_gem_address_space*msm_gem_address_space_get(struct msm_gem_address_space*a){return a;}
static u8*msm_gem_kernel_new(struct drm_device*d,unsigned size,u32 flags,struct msm_gem_address_space*a,struct drm_gem_object**obj,uint64_t*iova){(void)d;assert(size==4096);assert(flags==(MSM_BO_WC|(a?0:MSM_BO_STOLEN)));*obj=&bo;*iova=a?0x1000000:0xd4d00000;return fail?(void*)(intptr_t)-ENOMEM:(void*)1;}
static void msm_gem_object_set_name(struct drm_gem_object*o,const char*n){assert(o==&bo&&!strcmp(n,"tx_gem"));}
'''
with tempfile.TemporaryDirectory() as td:
    c,exe=Path(td)/'dma.c',Path(td)/'dma'
    c.write_text(dma_prefix+allocator+r'''
int main(void){struct msm_gem_address_space a={0};struct msm_kms k={0};struct msm_drm_private p={.kms=&k};struct drm_device d={.dev_private=&p};struct msm_dsi_host h={.dev=&d};
 assert(!dsi_tx_buf_alloc_6g(&h,4096));assert(h.tx_iova==0xd4d00000&&h.tx_size==4096);
 k.aspace=&a;assert(!dsi_tx_buf_alloc_6g(&h,4096));assert(h.tx_iova==0x1000000);
 fail=true;assert(dsi_tx_buf_alloc_6g(&h,4096)==-ENOMEM&&!h.tx_gem_obj);return 0;}
''')
    subprocess.run(['cc','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS real DSI DMA allocator stays contiguous without display MMU; mapped displays retain normal buffers; allocation errors release object ownership')

boot=(W/'scripts/alpine-drm-console.sh').read_text()
def write_exec(path,content):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);path.chmod(0o755)
with tempfile.TemporaryDirectory() as td:
    for case in ('gpu','manual','provider_fail','usb_timeout','legacy'):
        r=Path(td)/case
        for path in ('etc/libra','proc','run','dev','sys/class/backlight/bl','usr/sbin','bin'):(r/path).mkdir(parents=True,exist_ok=True)
        (r/'proc/cmdline').write_text('libra.gpu_defer=1' if case!='legacy' else '')
        if case in ('gpu','provider_fail','usb_timeout'):(r/'etc/libra/gpu-desktop').write_text('1\n')
        if case!='usb_timeout':(r/'run/libra-usb-ready').touch()
        (r/'dev/tty1').touch();(r/'sys/class/backlight/bl/brightness').write_text('512\n')
        write_exec(r/'bin/sleep','#!/bin/sh\nexit 0\n')
        write_exec(r/'usr/sbin/libra-gpu-prepare','#!/bin/sh\necho prepare >> "$TRACE"\n[ "$CASE" != provider_fail ]\n')
        write_exec(r/'usr/sbin/libra-drm-load','#!/bin/sh\nprintf "%s:%s\\n" "$1" "${LIBRA_GPU:-0}" >> "$TRACE"\n')
        write_exec(r/'usr/sbin/libra-drm-test','#!/bin/sh\necho test >> "$TRACE"\n')
        script=boot
        for path in ('etc','proc','run','dev','sys','usr/sbin'):script=script.replace('/'+path+'/',str(r)+'/'+path+'/')
        target=r/'boot.sh';target.write_text(script)
        proc=subprocess.run(['sh',str(target)],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH'],CASE=case,TRACE=str(r/'trace')),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        assert proc.returncode==(1 if case in ('provider_fail','usb_timeout') else 0),(case,proc.stdout)
        trace=(r/'trace').read_text().splitlines() if (r/'trace').exists() else []
        if case=='gpu':assert trace==['prepare','bias:1','backlight:1','panel:1','release:1','console:1','test'],trace
        if case=='provider_fail':assert trace==['prepare'],trace
        if case in ('manual','usb_timeout'):assert not trace,trace
        if case=='legacy':assert trace==['bias:0','backlight:0','panel:0','release:0','console:0','test'],trace
        assert (r/'sys/class/backlight/bl/brightness').read_text().strip()==('0' if proc.returncode else '512')
print('PASS actual boot helper: GPU providers before release/MSM, USB gate, manual mode untouched, errors stop before modeset, legacy mode preserved')
