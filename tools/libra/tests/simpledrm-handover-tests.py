# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import tempfile,subprocess,os
R=Path(__file__).resolve().parents[4];source=(R/'scripts/alpine-drm-load.sh').read_text()
def exe(p,s):p.parent.mkdir(parents=True, exist_ok=True);p.write_text(s);p.chmod(0o755)
with tempfile.TemporaryDirectory(prefix='libra-simpledrm-handover-') as temp:
 for case in ('good','absent','msm_loaded','unbind_fail','remains_bound','kernel_warning','kernel_timeout'):
  d=Path(temp)/case;d.mkdir();(d/'proc/sys/kernel').mkdir(parents=True);(d/'proc/cmdline').write_text('libra.drm_native=1\n');(d/'proc/sys/kernel/tainted').write_text('0\n');(d/'sys/class/backlight/backlight').mkdir(parents=True);(d/'sys/class/backlight/backlight/brightness').write_text('512\n');(d/'bin').mkdir();(d/'usr/sbin').mkdir(parents=True)
  parent=d/'sys/bus/platform/drivers/simple-framebuffer';parent.mkdir(parents=True);device=parent/'3400000.framebuffer';device.mkdir()
  if case!='absent':(device/'driver').symlink_to(parent)
  if case=='unbind_fail':(parent/'unbind').mkdir()
  else:(parent/'unbind').write_text('')
  if case=='msm_loaded':(d/'sys/module/msm').mkdir(parents=True)
  exe(d/'bin/dmesg','#!/bin/sh\necho old-harmless\n');exe(d/'bin/sleep','#!/bin/sh\nexit 0\n')
  exe(d/'usr/sbin/libra-kmsg',r'''#!/bin/sh
log=$1;shift
echo called > "$FIXTURE/capture-called"
"$@" > "$log" 2>&1;result=$?
if [ "$result" -eq 0 ] && [ "$CASE" != remains_bound ] && [ "$CASE" != absent ]; then rm "$FIXTURE/sys/bus/platform/drivers/simple-framebuffer/3400000.framebuffer/driver"; fi
[ "$CASE" != kernel_warning ] || echo 'WARNING: simulated failure during release' >> "$log"
[ "$CASE" != kernel_timeout ] || echo 'DSI timeout status=0x1' >> "$log"
cat "$log"
exit "$result"
''')
  p=d/'load.sh';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(source.replace('/sys/',str(d)+'/sys/').replace('/proc/',str(d)+'/proc/').replace('/run/',str(d)+'/run/').replace('/usr/sbin/',str(d)+'/usr/sbin/').replace('/dev/',str(d)+'/dev/'))
  env=dict(os.environ,PATH=str(d/'bin')+':'+os.environ['PATH'],FIXTURE=str(d),CASE=case)
  result=subprocess.run(['sh',str(p),'release'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  assert result.returncode==(0 if case in ('good','absent') else 1),(case,result.stdout)
  assert (d/'sys/class/backlight/backlight/brightness').read_text().strip()=='0',case
  assert (d/'capture-called').exists()==(case!='msm_loaded'),case
  if case=='good':assert (parent/'unbind').read_text()=='3400000.framebuffer'
  if case=='absent':assert not (parent/'unbind').read_text()
  print('PASS firmware release',case)
# The change reuses the verified order and excludes native power-cycling.
boot=(R/'scripts/alpine-drm-console.sh').read_text()
assert 'bias backlight panel release console' in boot
assert 'libra-drm-test console-start' not in boot
assert 'console-start' not in (R/'scripts/alpine-drm-test.sh').read_text()
print('PASS automatic simpledrm release precedes MSM registration; no console-start cycle')
# The panel opt-in is authorized only by a currently bound firmware driver.
with tempfile.TemporaryDirectory(prefix='libra-panel-optin-') as temp:
 for case in ('bound','absent','load_failure'):
  d=Path(temp)/case;d.mkdir();(d/'proc/sys/kernel').mkdir(parents=True);(d/'proc/cmdline').write_text('libra.drm_native=1\n');(d/'proc/sys/kernel/tainted').write_text('0\n');(d/'sys/class/backlight/backlight').mkdir(parents=True);(d/'sys/class/backlight/backlight/brightness').write_text('512\n');(d/'bin').mkdir();(d/'sbin').mkdir();(d/'usr/sbin').mkdir(parents=True)
  if case!='absent':
   parent=d/'sys/bus/platform/drivers/simple-framebuffer';device=parent/'3400000.framebuffer';device.mkdir(parents=True);(device/'driver').symlink_to(parent)
  exe(d/'bin/dmesg','#!/bin/sh\necho harmless\n')
  exe(d/'sbin/modprobe','#!/bin/sh\necho "$*" > "$FIXTURE/args"\n[ "$CASE" != load_failure ]\n')
  exe(d/'usr/sbin/libra-kmsg','#!/bin/sh\nlog=$1;shift\n"$@" > "$log" 2>&1;result=$?\ncat "$log"\nexit "$result"\n')
  p=d/'load.sh';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(source.replace('/sys/',str(d)+'/sys/').replace('/proc/',str(d)+'/proc/').replace('/run/',str(d)+'/run/').replace('/usr/sbin/',str(d)+'/usr/sbin/').replace('/sbin/modprobe',str(d)+'/sbin/modprobe').replace('/dev/',str(d)+'/dev/'))
  result=subprocess.run(['sh',str(p),'panel'],env=dict(os.environ,PATH=str(d/'bin')+':'+os.environ['PATH'],FIXTURE=str(d),CASE=case),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  assert result.returncode==(1 if case=='load_failure' else 0),(case,result.stdout)
  assert (d/'args').read_text().strip()==('panel_sharp_libra_rsp61322' if case=='absent' else 'panel_sharp_libra_rsp61322 firmware_handoff=1')
  if case=='load_failure':assert (d/'sys/class/backlight/backlight/brightness').read_text().strip()=='0'
  print('PASS conditional firmware panel opt-in',case)
