#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the real TSENS probe with manual/read-only flags and check the DT variant."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
subprocess.run(['python3', str(workspace / 'scripts/prepare-libra-thermal-observe-dtb.py')], check=True, stdout=subprocess.DEVNULL)
source = (workspace / 'linux/drivers/thermal/qcom/tsens.c').read_text()
body = source[source.index('static int tsens_probe('):source.index('static void tsens_remove(')]
prefix = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
typedef uint32_t u32;
#define GFP_KERNEL 0
#define IS_ERR(p) false
#define dev_err(...) ((void)0)
#define dev_info(...) ((void)0)
#define dev_err_probe(d,r,...) (r)
#define struct_size(p,m,n) sizeof(*(p))
struct device_node {int unused;};
struct device {struct device_node *of_node;struct device *parent;};
struct platform_device {struct device dev;};
struct tsens_priv;
struct tsens_ops {int(*init)(struct tsens_priv*);int(*calibrate)(struct tsens_priv*);int(*get_temp)(void);};
struct sensor {unsigned hw_id;struct tsens_priv *priv;};
struct tsens_plat_data {u32 num_sensors;const struct tsens_ops *ops;unsigned *hw_ids;void *feat,*fields;};
struct of_device_id {struct tsens_plat_data *data;};
struct tsens_priv {struct device *dev;u32 num_sensors;const struct tsens_ops *ops;bool observation_only;struct sensor sensor[16];void*feat,*fields;};
static bool msm8992_probe,msm8992_observe;static unsigned allocs,reads,writes,registered,debugged;
static struct tsens_priv priv;static struct of_device_id tsens_table[1];static int fail_init,fail_calibrate;
static int init(struct tsens_priv*p){reads++;return fail_init;}
static int calibrate(struct tsens_priv*p){reads++;return fail_calibrate;}
static int temp(void){return 40000;}
static const struct tsens_ops ops={init,calibrate,temp};
static unsigned ids[]={0,1,2,3,4,5,7,9,10,11,12,13,14};
static struct tsens_plat_data data_8992={13,&ops,ids,0,0},data_8960={1,&ops,0,0,0};
static struct of_device_id id={&data_8992};
static const struct of_device_id *of_match_node(void*t,struct device_node*np){return &id;}
static int of_property_read_u32(struct device_node*np,const char*key,u32*v){return -ENOENT;}
static void*devm_kzalloc(struct device*d,unsigned n,int flags){allocs++;memset(&priv,0,sizeof priv);return &priv;}
static void platform_set_drvdata(struct platform_device*p,void*v){assert(v==&priv);}
static void tsens_debug_init(struct platform_device*p){debugged++;}
static int tsens_register(struct tsens_priv*p){registered++;writes++;return 0;}
'''
main = r'''
int main(void){
 struct device_node node;struct platform_device p={.dev={.of_node=&node}};
 assert(tsens_probe(&p)==-ENODEV);assert(!allocs&&!reads&&!writes&&!registered);
 msm8992_probe=true;msm8992_observe=true;
 assert(!tsens_probe(&p));assert(priv.observation_only&&reads==2&&!writes&&!registered&&debugged==1);
 for(unsigned i=0;i<13;i++)assert(priv.sensor[i].priv==&priv&&priv.sensor[i].hw_id==ids[i]);
 fail_init=-EIO;assert(tsens_probe(&p)==-EIO&&!writes&&!registered);fail_init=0;
 fail_calibrate=-EINVAL;assert(tsens_probe(&p)==-EINVAL&&!writes&&!registered);fail_calibrate=0;
 msm8992_observe=false;assert(!tsens_probe(&p)&&registered==1&&writes==1);
 id.data=&data_8960;msm8992_probe=false;msm8992_observe=true;
 assert(!tsens_probe(&p)&&!priv.observation_only&&registered==2);
 puts("PASS actual TSENS probe: manual gate runs before mapping, observation stops before IRQ/zone registration, errors stay read-only, other SoCs unaffected");
}
'''
path = workspace / 'build/validation/thermal-observe-probe.c'
path.write_text(prefix+body+main)
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-sign-compare',str(path),'-o',str(path.with_suffix(''))],check=True)
subprocess.run([str(path.with_suffix(''))],check=True)
assert 'int __init init_common(' not in source, 'deferred/manual probes must not call discarded init text'
assert 'tsens_version(priv) >= VER_0_1 && !priv->observation_only' in source
show = source[source.index('static int dbg_readings_show('):source.index('DEFINE_SHOW_ATTRIBUTE(dbg_readings)')]
assert 'regmap_write' not in show and 'regmap_read' in show
variant = workspace / 'build/libra-thermal-observe.dtb'
original = workspace / 'build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb'
def prop(dtb,node,key,kind='s'):
 return subprocess.check_output(['fdtget','-t',kind,str(dtb),node,key],text=True).strip()
aux = prop(original,'/clock-controller','phandle','x')
for cpu in (0,1,2,3,0x100,0x101):assert prop(variant,f'/cpus/cpu@{cpu:x}','clocks','x')==aux
for node in ('/soc/clock-controller@f9015000','/cpufreq@f9019000'):assert prop(variant,node,'status')=='disabled'
assert prop(variant,'/soc/thermal-sensor@fc4a9000','status')=='okay'
print('PASS observation DTB keeps all CPU clocks on auxiliary source and disables both cluster/CCI/DVFS probes; manual init code retained at runtime')
