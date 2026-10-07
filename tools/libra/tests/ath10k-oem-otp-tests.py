#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replay OTP handling: OEM image policy leaves upload/execute errors intact."""
from pathlib import Path
import re
import subprocess
import tempfile
import os

workspace = Path(__file__).resolve().parents[4]
core = (workspace / 'linux/drivers/net/wireless/ath/ath10k/core.c').read_text()
oem = (workspace / 'kernel_xiaomi_msm8992/drivers/staging/qcacld-2.0/CORE/SERVICES/BMI/ol_fw.c').read_text()
assert re.search(r'address = BMI_SEGMENTED_WRITE_ADDR;\s*param = 0x0;\s*BMIExecute\(scn->hif_hdl, address, &param, scn\);\s*}', oem)
header = (workspace / 'linux/drivers/net/wireless/ath/ath10k/core.h').read_text()
assert re.search(r'ATH10K_FW_FEATURE_IGNORE_OTP_RESULT\s*=\s*7', header)
start = core.index('static int ath10k_download_and_run_otp(')
body = core[start:core.index('\n}\n', start) + 3]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
#define ATH10K_FW_FEATURE_IGNORE_OTP_RESULT 7
#define ATH10K_PRE_CAL_MODE_DT 1
#define ATH10K_PRE_CAL_MODE_FILE 2
#define ATH10K_PRE_CAL_MODE_NVMEM 3
#define BMI_PARAM_FLASH_SECTION_ALL 0x10000
#define ATH10K_DBG_BOOT 1
#define ath10k_err(...) ((void)0)
#define ath10k_warn(...) ((void)0)
#define ath10k_dbg(...) ((void)0)
struct fw_file {const void*otp_data;size_t otp_len;unsigned long fw_features[1];};
struct fw {const void*board_data;size_t board_len;struct fw_file fw_file;};
struct ath10k {struct {u32 patch_load_addr,otp_exe_param;}hw_params;struct fw*running_fw;int cal_mode;};
static int stage,fail,skip_otp;static u32 response,last_param;
static int test_bit(int bit,const unsigned long*map){return !!(*map&(1ul<<bit));}
static int ath10k_download_board_data(struct ath10k*a,const void*p,size_t n){assert(!stage&&p&&n);stage=1;return fail==1?-EIO:0;}
static int ath10k_bmi_fast_download(struct ath10k*a,u32 addr,const void*p,size_t n){assert(stage==1&&addr==a->hw_params.patch_load_addr&&p&&n);stage=2;return fail==2?-EIO:0;}
static int ath10k_bmi_execute(struct ath10k*a,u32 addr,u32 param,u32*out){assert(stage==2&&addr==a->hw_params.patch_load_addr);stage=3;last_param=param;*out=response;return fail==3?-EIO:0;}
'''
main = r'''
int main(void){char data=1;struct fw fw={.board_data=&data,.board_len=1,.fw_file={.otp_data=&data,.otp_len=1}};
 struct ath10k ar={.hw_params={0x1234,0},.running_fw=&fw};
 response=2;assert(ath10k_download_and_run_otp(&ar)==-EINVAL&&stage==3);
 for(int policy=0;policy<2;policy++){
  skip_otp=!policy;fw.fw_file.fw_features[0]=policy?1ul<<7:0;
  stage=fail=0;assert(!ath10k_download_and_run_otp(&ar)&&stage==3&&last_param==0);
  for(fail=1;fail<=3;fail++){stage=0;assert(ath10k_download_and_run_otp(&ar)==-EIO&&stage==fail);}
 }
 stage=fail=skip_otp=0;fw.fw_file.fw_features[0]=0;response=0;assert(!ath10k_download_and_run_otp(&ar)&&stage==3);
 puts("PASS actual OTP callback: OEM firmware flag and temporary skip parameter still upload board/OTP and execute param0; all transfer/execute errors propagate; default policy rejects nonzero results");}
'''
target = workspace / 'build/validation/ath10k-oem-otp.c'
target.write_text(prefix + body + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
for script in ('configure-debian-rootfs.sh', 'install-libra-radio-update.sh'):
    assert 'update-alternatives --set regulatory.db /lib/firmware/regulatory.db-upstream' in (workspace / 'scripts' / script).read_text()
print('PASS fresh-image/upgrade select upstream-signed regdb without changing kernel signature validation')

# Execute the startup helper with fake sysfs/proc and hardware commands.
# The observed old failure had a bound host + Root Port, but no radio PHY.
helper = (workspace / 'linux/tools/libra/debian/usr/sbin/libra-radio-start').read_text()
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    sysfs = root / 'sys'
    for name in ('bus/platform/devices/fc520000.pcie/driver',
                 'bus/platform/drivers_probe',
                 'bus/pci/devices/0000:00:00.0/vendor',
                 'module/pcie_qcom/parameters/msm8992_probe'):
        file = sysfs / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('')
    cmdline = root / 'cmdline'
    cmdline.write_text('libra.radio=1')
    script = root / 'start'
    script.write_text(helper.replace('/sys/', str(sysfs) + '/').replace('/proc/cmdline', str(cmdline)))
    binpath = root / 'bin'
    binpath.mkdir()
    log = root / 'calls'
    for name in ('modprobe', 'udevadm', 'sleep'):
        file = binpath / name
        file.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$TEST_LOG"\n')
        file.chmod(0o755)
    env = dict(os.environ, PATH=str(binpath) + ':/usr/bin:/bin', TEST_LOG=str(log))
    result = subprocess.run(['/bin/sh', str(script)], env=env, text=True, capture_output=True)
    assert result.returncode == 1 and 'did not register' in result.stderr
    assert log.read_text().count('modprobe hci_uart') == 1
    (sysfs / 'bus/pci/devices/0000:01:00.0/ieee80211').mkdir(parents=True)
    result = subprocess.run(['/bin/sh', str(script)], env=env, text=True, capture_output=True)
    assert result.returncode == 0 and 'firmware registered' in result.stdout
    cmdline.write_text('libra.radio=0')
    log.write_text('')
    result = subprocess.run(['/bin/sh', str(script)], env=env, text=True, capture_output=True)
    assert result.returncode == 0 and not log.read_text()
print('PASS actual startup helper: Root Port alone is insufficient; registered Wi-Fi PHY succeeds; radio=0 avoids hardware commands')
