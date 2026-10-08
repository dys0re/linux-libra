#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the DSI DMA lookup and fbdev cleanup ownership transitions."""
from pathlib import Path
import subprocess
import tempfile

W = Path(__file__).resolve().parents[4]
dsi = (W / 'linux/drivers/gpu/drm/msm/dsi/dsi_host.c').read_text()
fb = (W / 'linux/drivers/gpu/drm/msm/msm_fbdev.c').read_text()


def function(text, name):
    start = text.rfind('\n', 0, text.index(name + '(')) + 1
    if text[start:].startswith('{'):
        raise AssertionError(name)
    end = text.index('\n}\n', start) + 3
    return text[start:end]


prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <stdlib.h>
struct drm_gem_object { int pins; };
struct msm_dsi_host { struct drm_gem_object *tx_gem_obj; uint64_t tx_iova; };
struct drm_framebuffer { struct drm_gem_object *bo; };
struct msm_kms { void *aspace; };
struct msm_drm_private { struct msm_kms *kms; };
struct drm_device { struct msm_drm_private *dev_private; };
struct drm_fb_helper { struct drm_framebuffer *fb; struct drm_device *dev; int client; };
struct fb_info { void *par; };
#define DBG() do {} while (0)
static int sequence, released;
static struct drm_gem_object *msm_framebuffer_bo(struct drm_framebuffer *f,int i) { assert(i==0); return f->bo; }
static void drm_fb_helper_fini(struct drm_fb_helper *h) { (void)h; assert(sequence++==0); }
static void msm_gem_put_vaddr(struct drm_gem_object *o) { assert(sequence++==1 && o->pins==2); o->pins--; }
static void msm_gem_unpin_iova(struct drm_gem_object *o,void *a) { assert(a==(void*)1 && sequence++==2 && o->pins==1); o->pins--; }
static void drm_framebuffer_remove(struct drm_framebuffer *f) { assert(sequence++==3 && f->bo->pins==0); released++; }
static void drm_client_release(int *p) { (void)p; assert(sequence++==4); }
static void drm_fb_helper_unprepare(struct drm_fb_helper *h) { (void)h; assert(sequence++==5); }
#define kfree(p) do { assert(sequence++==6); free(p); } while (0)
'''
main = r'''
int main(void) {
 struct drm_gem_object o={.pins=2}; struct msm_dsi_host d={.tx_gem_obj=&o,.tx_iova=0xd4d01000}; uint64_t addr;
 for(int i=0;i<10000;i++){ assert(!dsi_dma_base_get_6g(&d,&addr)); assert(addr==d.tx_iova && o.pins==2); }
 assert(dsi_dma_base_get_6g(&d,NULL)==-EINVAL); d.tx_gem_obj=NULL; assert(dsi_dma_base_get_6g(&d,&addr)==-EINVAL);
 struct msm_kms kms={.aspace=(void*)1}; struct msm_drm_private priv={.kms=&kms}; struct drm_device dev={.dev_private=&priv};
 struct drm_framebuffer f={.bo=&o}; struct drm_fb_helper *h=calloc(1,sizeof(*h)); h->fb=&f;h->dev=&dev; struct fb_info info={.par=h};
 msm_fbdev_fb_destroy(&info); assert(sequence==7 && released==1 && !o.pins); return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp) / 'lifecycle.c', Path(tmp) / 'lifecycle'
    c.write_text(prefix + function(dsi, 'dsi_dma_base_get_6g') +
                 function(fb, 'msm_fbdev_fb_destroy') + main)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS actual callbacks: 10000 DSI DMA address lookups add no pins; fbdev releases vaddr/IOVA before framebuffer destruction')

bootstrap = function(dsi, 'dsi_get_config_8992')
assert 'devm_clk_bulk_get(' not in bootstrap
assert 'clk_bulk_get(' in bootstrap and 'clk_bulk_put(' in bootstrap
driver = (W / 'linux/drivers/gpu/drm/msm/msm_drv.c').read_text()
uninit = function(driver, 'msm_drm_uninit')
assert uninit.index('component_unbind_all(') < uninit.index('msm_deinit_vram(')
test = (W / 'linux/tools/libra/debian/usr/sbin/libra-gpu-test').read_text()
assert 'modprobe -r' not in test and '/unbind' not in test
assert '[ ! -d /sys/module/msm ]' in test and 'libra.gpu_defer=1' in test
assert 'kernel/tainted' in test
print('PASS temporary clock ownership, component-before-VRAM cleanup, cold GPU test refusing driver unload or tainted kernel')
