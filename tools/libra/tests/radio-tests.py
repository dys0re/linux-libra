#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare radio programming to OEM and exercise real power/identity callbacks."""
from pathlib import Path
import importlib.util
import re
import runpy
import struct
import subprocess
import tempfile

workspace = Path(__file__).resolve().parents[4]
linux = workspace / 'linux'
validation = workspace / 'build/validation'
validation.mkdir(exist_ok=True)


def function(source, name):
    start = source.index('static int ' + name + '(')
    return source[start:source.index('\n}\n', start) + 3]


# Compare all 48 writes and their order to the independent OEM vbg-opt branch.
oem = (workspace / 'kernel_xiaomi_msm8992/drivers/pci/host/pci-msm.c').read_text()
start = oem.rfind('static void pcie_phy_init', 0, oem.index('RC%d: Initializing 20nm'))
body = oem[start:oem.index('static bool pcie_phy_is_ready', start)]
body = re.sub(r'if \(dev->vbg_opt\) \{(.*?)\} else \{.*?\}', r'\1', body, flags=re.S)
registers = dict(re.findall(r'^#define\s+(\w+)\s+(0x[0-9a-fA-F]+)', oem, re.M))
expected = [(int(registers[n], 16), int(v, 16)) for n, v in re.findall(
    r'msm_pcie_write_reg\(dev->phy,\s*(\w+),\s*(0x[0-9a-fA-F]+)\);', body)]
phy = (linux / 'drivers/phy/qualcomm/phy-qcom-pcie-20nm.c').read_text()
actual = [(int(r, 16), int(v, 16)) for r, v in re.findall(r'\{ (0x\w+), (0x\w+) \}', phy)]
assert len(expected) == 48 and actual == expected
print('PASS PCIe PHY: every register/value/order matches OEM 20nm vbg-opt sequence')

# Run actual Wi-Fi/BT callbacks with shared PA votes and injected regulator errors.
wlan = (linux / 'drivers/regulator/qca6174-wlan-power.c').read_text()
bt = (linux / 'drivers/bluetooth/hci_qca.c').read_text()
cnss = (workspace / 'kernel_xiaomi_msm8992/drivers/net/wireless/cnss/cnss_pci.c').read_text()
resources = function(cnss, 'cnss_wlan_get_resources')
assert resources.index('regulator_enable(vreg_info->wlan_reg)') < resources.index('regulator_enable(vreg_info->wlan_reg_io)') < resources.index('regulator_enable(vreg_info->wlan_reg_xtal)') < resources.index('cnss_wlan_bootstrap_gpio_init(i)')
oem_probe = function(cnss, 'cnss_probe')
assert oem_probe.index('cnss_wlan_get_resources(pdev)') < oem_probe.index('cnss_wlan_gpio_set(&penv->gpio_info, WLAN_EN_HIGH)')
probe = function(wlan, 'qca6174_wlan_probe')
assert '"bootstrap", GPIOD_OUT_LOW' in probe and 'gpiod_set_value_cansleep' not in probe
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct regulator{int id,votes;};struct regulator_bulk_data{struct regulator*consumer;};
struct gpio_desc{int value,id;};struct gpio_descs{unsigned ndescs;struct gpio_desc**desc;};
struct qca6174_wlan_power{struct regulator_bulk_data supplies[3];struct gpio_desc*enable;struct gpio_descs*bootstrap;bool enabled;};
struct regulator_dev{struct qca6174_wlan_power*p;};
struct qca_power{struct regulator_bulk_data*vreg_bulk;int num_vregs;bool vregs_on;};
struct qca_serdev{struct qca_power*bt_power;struct gpio_desc*bt_en;};
static int fail=-1,steps,order[32],delays,trace[64],traces;
static struct regulator*rails[3];static struct gpio_desc*straps[3];
static void* rdev_get_drvdata(struct regulator_dev*r){return r->p;}
static int regulator_enable(struct regulator*r){trace[traces++]=100+r->id;order[steps++]=r->id;if(r->id==fail)return -EIO;r->votes++;return 0;}
static int regulator_disable(struct regulator*r){for(int i=0;i<3;i++)assert(!straps[i]->value);assert(r->votes>0);r->votes--;return 0;}
static void gpiod_set_value_cansleep(struct gpio_desc*g,int n){
 trace[traces++]=200+g->id*10+n;
 if(g->id>=2&&n)for(int i=0;i<3;i++)assert(rails[i]->votes>0);
 if(g->id==0&&n)for(int i=0;i<3;i++)assert(straps[i]->value);
 g->value=n;}
static void usleep_range(int lo,int hi){assert(lo==10000&&hi==11000);trace[traces++]=10000;delays++;}
static void msleep(int ms){assert(ms==50||ms==10);trace[traces++]=1000+ms;delays++;}
'''
main = r'''
int main(void){
 struct regulator pa={0,0},io={1,0},xo={2,0};struct gpio_desc wg={0,0},bg={0,1},bs[]={{0,2},{0,3},{0,4}};
 rails[0]=&pa;rails[1]=&io;rails[2]=&xo;for(int i=0;i<3;i++)straps[i]=&bs[i];struct gpio_descs gpios={3,straps};
 struct qca6174_wlan_power w={.supplies={{&pa},{&io},{&xo}},.enable=&wg,.bootstrap=&gpios};struct regulator_dev rd={&w};
 struct regulator_bulk_data br[]={{&io},{&xo},{&pa}};struct qca_power bp={br,3,false};struct qca_serdev b={&bp,&bg};
 for(int f=0;f<3;f++){fail=f;steps=delays=0;assert(qca6174_wlan_enable(&rd)==-EIO);assert(!pa.votes&&!io.votes&&!xo.votes&&!wg.value&&!w.enabled);}
 fail=-1;steps=delays=traces=0;assert(!qca6174_wlan_enable(&rd));assert(order[0]==0&&order[1]==1&&order[2]==2&&wg.value&&w.enabled&&delays==4);
 int expected[]={100,101,102,221,1010,231,1010,241,1010,201,10000};assert(traces==11);for(int i=0;i<11;i++)assert(trace[i]==expected[i]);
 steps=delays=0;assert(!qca_rome_power_on(&b));assert(order[0]==1&&order[1]==2&&order[2]==0&&bg.value&&delays==2);assert(pa.votes==2);
 assert(!qca6174_wlan_disable(&rd));assert(!wg.value&&bg.value&&pa.votes==1&&io.votes==1&&xo.votes==1);
 for(int i=0;i<3;i++)assert(!bs[i].value);
 steps=delays=traces=0;assert(!qca6174_wlan_enable(&rd));assert(wg.value&&pa.votes==2&&io.votes==2&&xo.votes==2);
 assert(!qca6174_wlan_disable(&rd));assert(!wg.value&&bg.value&&pa.votes==1&&io.votes==1&&xo.votes==1);
 steps=0;assert(!qca_rome_power_on(&b));assert(!steps); /* no duplicate votes */
 /* Model Bluetooth off using the exact reverse order of its three rails. */
 for(int i=2;i>=0;i--)regulator_disable(br[i].consumer);bp.vregs_on=false;bg.value=0;
 for(int f=0;f<3;f++){fail=f;steps=delays=0;assert(qca_rome_power_on(&b)==-EIO);assert(!pa.votes&&!io.votes&&!xo.votes&&!bp.vregs_on&&!bg.value);}
 puts("PASS actual WLAN/Rome power callbacks: OEM rails before each strap10ms before WLAN_EN10ms, no early probe highs, straps cleared before IO-off, rollback and shared Bluetooth votes survive repeated WLAN cycles");}
'''
target = validation / 'radio-power.c'
target.write_text(prefix + function(wlan, 'qca6174_wlan_enable') + function(wlan, 'qca6174_wlan_disable') + function(bt, 'qca_rome_power_on') + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-Wno-misleading-indentation', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)

# Execute the PHY status reader while on/off. Allowed offsets come from OEM
# register names, and any MMIO read outside the powered/locked state fails.
status_regs = ['QSERDES_COM_RESET_SM', 'QSERDES_COM_CORE_VCO_TUNE',
               'QSERDES_RX_RX_SIGDET', 'PCIE_PHY_SW_RESET',
               'PCIE_PHY_POWER_DOWN_CONTROL', 'PCIE_PHY_START',
               'PCIE_PHY_ENDPOINT_REFCLK_DRIVE', 'PCIE_PHY_PCS_STATUS',
               'PCIE_PHY_PCS_STATUS2', 'PCIE_PHY_REVISION_ID0',
               'PCIE_PHY_REVISION_ID1', 'PCIE_PHY_REVISION_ID2',
               'PCIE_PHY_REVISION_ID3']
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef uint16_t u16; typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct device{void*data;};struct phy{int mutex,power_count;};
struct msm8992_pcie_phy{void*base;struct phy*phy;};
struct seq_file{void*private;};
static struct phy*live;static unsigned reads,lines;
static const u16 allowed[]={ALLOWED};
static void*dev_get_drvdata(void*d){return ((struct device*)d)->data;}
static void mutex_lock(int*m){assert(!*m);*m=1;}
static void mutex_unlock(int*m){assert(*m==1);*m=0;}
static u32 readl(void*p){assert(live->power_count&&live->mutex==1&&reads<ARRAY_SIZE(allowed));
 assert((uintptr_t)p-0x1000==allowed[reads++]);return 0xa5;}
static void seq_puts(struct seq_file*s,const char*t){assert(!strcmp(t,"PHY is powered off\n"));lines++;}
static void seq_printf(struct seq_file*s,const char*fmt,...){assert(!strcmp(fmt,"PHY+%03x=%08x\n"));lines++;}
'''.replace('ALLOWED', ','.join(registers[n] for n in status_regs))
main = r'''
int main(void){struct phy phy={0};live=&phy;
 struct msm8992_pcie_phy p={.base=(void*)0x1000,.phy=&phy};struct device dev={&p};struct seq_file s={&dev};
 assert(!msm8992_pcie_phy_status_show(&s,0));assert(reads==0&&lines==1&&!phy.mutex);
 phy.power_count=1;lines=0;assert(!msm8992_pcie_phy_status_show(&s,0));
 assert(reads==ARRAY_SIZE(allowed)&&lines==reads&&!phy.mutex);
 puts("PASS actual PHY status reader: only selected OEM-readable offsets under PHY power mutex; no MMIO while powered off, no write API");}
'''
target = validation / 'radio-phy-status.c'
target.write_text(prefix + function(phy, 'msm8992_pcie_phy_status_show') + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-sign-compare', str(target),
                '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)

# Read factory images directly; round-trip IEs so wrapper bugs cannot hide.
spec = importlib.util.spec_from_file_location('firmware', workspace / 'scripts/extract-libra-radio-firmware.py')
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)
images = workspace / 'libra_images_6.1.7_20151221.0000.11_5.1_cn/images'
fat = fw.Fat16(images / 'NON-HLOS.bin')
output = workspace / 'build/libra-radio-firmware'
data = (output / 'ath10k/QCA6174/hw3.0/firmware-5.bin').read_bytes()
assert data[:12] == b'QCA-ATH10K\0\0'
ies = {}
offset = 12
while offset < len(data):
    kind, length = struct.unpack_from('<II', data, offset)
    offset += 8
    assert kind not in ies and offset + length <= len(data)
    ies[kind] = data[offset:offset + length]
    offset += (length + 3) & ~3
assert offset == len(data)
assert ies[3] == fat.read('image/qwlan30.bin') and ies[4] == fat.read('image/otp30.bin')
assert ies[5] == struct.pack('<I', 4) and ies[6] == struct.pack('<I', 3) and ies[2] == b'\x80'
assert (output / 'ath10k/QCA6174/hw3.0/board.bin').read_bytes() == fat.read('image/bdwlan30.bin')
btfat = fw.Fat16(images / 'BTFM.bin')
assert (output / 'qca/rampatch_00440302.bin').read_bytes() == btfat.read('image/btfw32.tlv')
assert (output / 'qca/btnv32.bin').read_bytes() == btfat.read('image/btnv32.bin')
try:
    fat.read('image/notthere.bin')
    raise AssertionError('missing file accepted')
except FileNotFoundError:
    pass
print('PASS OEM firmware: Wi-Fi/OTP/board and Bluetooth payloads exactly preserved, TLV/APIs/lengths and missing file handling checked')

# The management identity helper changes only an unconfigured controller.
identity = runpy.run_path(str(linux / 'tools/libra/debian/usr/sbin/libra-bluetooth-address'))
class Sock:
    def __init__(self, unconfigured=True, ready=True):
        self.unconfigured, self.ready, self.sent = unconfigured, ready, []
    def send(self, data):
        self.sent.append(data)
    def settimeout(self, seconds):
        assert 0 < seconds <= 5
    def recv(self, size):
        op, index, length = struct.unpack_from('<HHH', self.sent[-1])
        if op in (0x36, 3):
            present = self.unconfigured if op == 0x36 else not self.unconfigured and self.ready
            payload = struct.pack('<HH', 1, 0) if present else struct.pack('<H', 0)
        else:
            assert op == 0x39 and index == 0 and length == 6
            payload = b'\0' * 4
        body = struct.pack('<HB', op, 0) + payload
        return struct.pack('<HHH', 1, index, len(body)) + body
with tempfile.TemporaryDirectory() as temp:
    storage = Path(temp) / 'address'
    storage.write_text('02:11:22:33:44:55\n')
    sock = Sock(False)
    assert identity['configure'](sock, 0, storage)
    assert len(sock.sent) == 2
    sock = Sock(False, False)
    assert identity['configure'](sock, 0, storage) is False
    sock = Sock(True)
    assert identity['configure'](sock, 0, storage)
    assert sock.sent[-1][6:] == bytes.fromhex('554433221102')
print('PASS Bluetooth identity: existing address preserved, async setup wait, unconfigured-only management address and little-endian encoding')

# Python 3.13 cannot express HCI_CHANNEL_CONTROL in its ordinary bind tuple.
import ctypes
class BindSock:
    def fileno(self): return 42
def bind(fd, raw, length):
    assert fd == 42 and length == 6
    assert ctypes.string_at(raw, length) == struct.pack('=HHH', 31, 65535, 3)
    return 0
identity['bind_control'](BindSock(), bind)
print('PASS management sockaddr ABI: Linux HCI control channel through libc, compatible with Debian Python 3.13')

# Execute the actual PHY power callbacks, including all hardware timeout paths.
start = phy.index('static const struct {')
end = phy.index('static int msm8992_pcie_phy_probe(')
code = phy[start:phy.index('static const struct phy_ops', start)]
prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#include <errno.h>
typedef uint16_t u16;typedef uint8_t u8;typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1u<<(n))
#define dev_err(...) ((void)0)
struct clk {int dummy;};struct reset_control{int dummy;};
struct msm8992_pcie_phy{void*base;struct clk*pipe;struct reset_control*pipe_reset;};
struct phy{int dev;struct msm8992_pcie_phy*p;};
static int phase=1,reset_err,rate_err,clk_err,poll_err,enabled,writes,reset_on=1;
static struct msm8992_pcie_phy*phy_get_drvdata(struct phy*p){return p->p;}
static void writel(u32 v,void*p){uintptr_t off=(uintptr_t)p-0x1000;assert(phase>=1);assert(off<0x1000);writes++;}
static void usleep_range(int lo,int hi){assert(lo==995&&hi==1005&&writes==48);phase=2;}
static int reset_control_deassert(struct reset_control*r){assert(phase==2&&writes==48);phase=3;if(reset_err)return reset_err;reset_on=0;return 0;}
static int reset_control_assert(struct reset_control*r){reset_on=1;return 0;}
static int clk_set_rate(struct clk*c,unsigned long rate){assert(phase==3&&!reset_on&&rate==125000000);phase=4;return rate_err;}
static int clk_prepare_enable(struct clk*c){assert(phase==4&&!reset_on);if(clk_err)return clk_err;enabled++;phase=5;return 0;}
static void clk_disable_unprepare(struct clk*c){assert(enabled==1);enabled--;}
#define readl_poll_timeout(addr,status,condition,delay,timeout) ({assert((uintptr_t)(addr)==0x1728&&phase==5&&delay==1000&&timeout==100000);status=poll_err?BIT(6):0;assert(!!(condition)==!poll_err);poll_err;})
'''
main = r'''
int main(void){struct msm8992_pcie_phy p={.base=(void*)0x1000};struct phy f={.p=&p};
 assert(!msm8992_pcie_phy_power_on(&f)&&writes==48&&enabled==1);
 assert(!msm8992_pcie_phy_power_off(&f)&&writes==50&&!enabled&&reset_on);
 for(int stage=0;stage<4;stage++){phase=1;enabled=writes=0;reset_on=1;reset_err=rate_err=clk_err=poll_err=0;
 if(stage==0)reset_err=-EIO;if(stage==1)rate_err=-EIO;if(stage==2)clk_err=-EIO;if(stage==3)poll_err=-ETIMEDOUT;
 assert(msm8992_pcie_phy_power_on(&f)==(stage==3?-ETIMEDOUT:-EIO));assert(!enabled&&writes==50&&reset_on);}
 puts("PASS actual PCIe PHY power callbacks: calibration then PIPE reset release/gate, 125MHz setting, bounded ready polling, all failures stop without clock leak");}
'''
target = validation / 'radio-phy.c'
target.write_text(prefix + code + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-misleading-indentation', '-Wno-sign-compare', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)

# Management status packets have the same opcode/status layout as completion.
class StatusSock(Sock):
    def recv(self, size):
        opcode, index, length = struct.unpack_from('<HHH', self.sent[-1])
        return struct.pack('<HHHHB', 2, index, 3, opcode, 0x0b)
try:
    identity['command'](StatusSock(), 0x36)
    raise AssertionError('management error ignored')
except RuntimeError as err:
    assert 'status 0xb' in str(err)
print('PASS management command-status error is decoded and surfaced')

# Execute staged host power/clock sequence and inject each operation failure.
host = (linux / 'drivers/pci/controller/dwc/pcie-qcom.c').read_text()
prefix = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1u<<(n))
#define SZ_16M (16u*1024*1024)
#define PARF_PHY_CTRL 0x40
#define PARF_DBI_BASE_ADDR 0x168
#define PARF_SYS_CTRL 0x00
#define PARF_SLV_ADDR_SPACE_SIZE 0x16c
#define dev_err(...) ((void)0)
struct regulator_bulk_data{int id;};struct clk{int id;};struct clk_bulk_data{struct clk*clk;};struct reset_control{int x;};
struct qcom_pcie_resources_msm8992{struct reset_control*phy_reset;struct clk_bulk_data clks[6];struct regulator_bulk_data supplies[3];};
struct pci{int dev;};struct qcom_pcie{struct pci*pci;void*parf;union{struct qcom_pcie_resources_msm8992 msm8992;}res;};
static int stage,fail,rails,clocks,ref,ldo,reset_on=1,writes;static u32 values[0x200/4];
static void qcom_pcie_snapshot_msm8992(struct qcom_pcie*p,const char*name){}
static int regulator_bulk_enable(int n,struct regulator_bulk_data*p){assert(n==3&&stage==0);stage=1;if(fail==1)return -EIO;rails=1;return 0;}
static int regulator_bulk_disable(int n,struct regulator_bulk_data*p){assert(n==3&&rails);rails=0;return 0;}
static int clk_prepare_enable(struct clk*c){if(c->id==0){assert(stage==1);stage=2;if(fail==2)return -EIO;ref=1;}else{assert(c->id==5&&stage==2&&ref);stage=3;if(fail==3)return -EIO;ldo=1;}return 0;}
static void clk_disable_unprepare(struct clk*c){if(c->id==0){assert(ref);ref=0;}else{assert(c->id==5&&ldo);ldo=0;}}
static int clk_set_rate(struct clk*c,unsigned long rate){assert(c->id==1&&rate==1011000&&stage==4&&!reset_on&&ref&&ldo);stage=5;return fail==5?-EIO:0;}
static int clk_bulk_prepare_enable(int n,struct clk_bulk_data*p){assert(n==4&&p[0].clk->id==1&&stage==5&&!reset_on&&ref&&ldo);stage=6;if(fail==6)return -EIO;clocks=1;return 0;}
static void clk_bulk_disable_unprepare(int n,struct clk_bulk_data*p){assert(n==4&&clocks);clocks=0;}
static int reset_control_deassert(struct reset_control*r){assert(stage==3&&!clocks&&rails&&ref&&ldo);stage=4;if(fail==4)return -EIO;reset_on=0;return 0;}
static int reset_control_assert(struct reset_control*r){reset_on=1;return 0;}
static int qcom_scm_restore_sec_cfg(int id,int spare){assert(stage==6&&!reset_on&&id==11&&!spare);stage=7;return fail==7?-EIO:0;}
static u32 readl(void*p){return values[((uintptr_t)p-0x1000)/4];}
static void writel(u32 v,void*p){assert(stage==7&&!reset_on);writes++;values[((uintptr_t)p-0x1000)/4]=v;}
"""
main = r"""
int main(void){struct pci pci={0};struct qcom_pcie p={.pci=&pci,.parf=(void*)0x1000};struct clk cs[6];
 for(int i=0;i<6;i++){cs[i].id=i;p.res.msm8992.clks[i].clk=&cs[i];}
 for(fail=1;fail<=7;fail++){stage=rails=clocks=ref=ldo=writes=0;reset_on=1;assert(qcom_pcie_init_msm8992(&p)==-EIO);assert(!rails&&!clocks&&!ref&&!ldo&&!writes&&reset_on);}
 fail=stage=writes=0;assert(!qcom_pcie_init_msm8992(&p)&&rails&&clocks&&ref&&ldo&&!reset_on&&writes==4);
 assert(values[0]==0x365e&&values[0x168/4]==0&&values[0x16c/4]==SZ_16M);
 puts("PASS actual PCIe host init: reference/LDO then reset release then AUX program/gate and SCM11; all seven failure stages unwind without leaked votes");}
"""
target = validation / 'radio-host.c'
target.write_text(prefix + function(host, 'qcom_pcie_init_msm8992') + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
