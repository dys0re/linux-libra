# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import os, subprocess, tempfile, textwrap
ROOT=Path(__file__).resolve().parents[4]
source=(ROOT/'scripts/alpine-drm-test.sh').read_text()

def executable(p,s):p.parent.mkdir(parents=True, exist_ok=True);p.write_text(s);p.chmod(0o755)
with tempfile.TemporaryDirectory(prefix='libra-native-console-') as temp:
 root=Path(temp)
 for case in ('good','no_fb','wrong_fb','missing_plane','stall','underrun','fifo','bad_brightness','late_fault','video_done_fault','cmd_dma_fault','panel_shutdown_fault'):
  d=root/case;d.mkdir();binpath=d/'bin';binpath.mkdir();bl=d/'sys/class/backlight/backlight';(bl/'device/driver').mkdir(parents=True)
  (bl/'device/driver/module').symlink_to(d/'module/qcom_wled')
  for f,val in {'brightness':'0','actual_brightness':'0','bl_power':'0','max_brightness':'4095'}.items():(bl/f).write_text(val+'\n')
  (d/'sys/class/graphics/fb0').mkdir(parents=True)
  if case!='no_fb':(d/'sys/class/graphics/fb0/name').write_text('simpledrmdrmfb\n' if case=='wrong_fb' else 'msmdrmfb\n')
  (d/'sys/kernel/debug/dri/0').mkdir(parents=True);(d/'sys/kernel/debug/dri/0/state').write_text('fixture\n')
  executable(binpath/'cat',r'''#!/bin/sh
case "$1" in
 */dri/0/state)
  n=0; [ ! -f "$FIXTURE/state-count" ] || n=$(/bin/cat "$FIXTURE/state-count"); n=$((n+1)); echo "$n" > "$FIXTURE/state-count"
  fb=89; [ "$CASE" != missing_plane ] || fb=0
  frames=$((n*100)); [ "$CASE" != stall ] || frames=100
  underrun=0; [ "$CASE" != underrun ] || underrun=1
  printf 'plane[34]: plane-0\n\tcrtc=crtc-0\n\tfb=%s\ncrtc[88]: crtc-0\n\tactive=1\n\tunderrun_count=%s\n\tintf_frame_count=%s\nconnector[33]: DSI-1\n' "$fb" "$underrun" "$frames" ;;
 */actual_brightness) if [ "$CASE" = bad_brightness ]; then echo 0; else /bin/cat "${1%actual_brightness}brightness"; fi ;;
 *) exec /bin/cat "$@" ;;
esac
''')
  executable(binpath/'dmesg',r'''#!/bin/sh
printf 'old harmless log\n'
n=0; [ ! -f "$FIXTURE/dmesg-count" ] || n=$(/bin/cat "$FIXTURE/dmesg-count"); n=$((n+1)); echo "$n" > "$FIXTURE/dmesg-count"
if [ "$n" -gt 1 ]; then
 case "$CASE" in
  video_done_fault) echo 'wait for video done timed out' ;;
  cmd_dma_fault) echo 'cmd dma tx failed, type=0x5, data0=0x28, ret=-110' ;;
  panel_shutdown_fault) echo 'panel shutdown command failed: -110; forcing power-off' ;;
 esac
fi
if [ "$CASE" = fifo ] && [ "$n" -gt 1 ]; then echo 'DSI FIFO status=0x44441000'; fi
if [ "$CASE" = late_fault ] && [ "$(/bin/cat "$FIXTURE/sys/class/backlight/backlight/brightness")" = 512 ]; then echo 'DSI timeout status=0x1'; fi
''')
  executable(binpath/'sleep','#!/bin/sh\nexit 0\n')
  executable(binpath/'ip','#!/bin/sh\nexit 0\n')
  executable(binpath/'modetest','#!/bin/sh\ntouch "$FIXTURE/unexpected-modetest"\nexit 99\n')
  script=d/'test.sh';script.write_text(source.replace('/sys/',str(d)+'/sys/').replace('/run/',str(d)+'/run/'))
  env=dict(os.environ,PATH=str(binpath)+':'+os.environ['PATH'],FIXTURE=str(d),CASE=case)
  p=subprocess.run(['sh',str(script),'console'],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  assert p.returncode==(0 if case=='good' else 1),(case,p.returncode,p.stdout)
  assert (bl/'brightness').read_text().strip()==('512' if case=='good' else '0'),(case,p.stdout)
  assert not (d/'unexpected-modetest').exists(),case
  if case=='good':assert 'Native console frame progress: 100 frames' in p.stdout,p.stdout
  print('PASS native console',case)
 # Validate actual bootstrap orchestration with and without USB readiness.
 boot=(ROOT/'scripts/alpine-drm-console.sh').read_text()
 for case in ('ready','timeout','stage_failure','release_failure','console_failure'):
  d=root/('boot-'+case);d.mkdir();(d/'run').mkdir();(d/'proc').mkdir();(d/'proc/cmdline').write_text('libra.drm_native=1\n');bl=d/'sys/class/backlight/backlight';bl.mkdir(parents=True);(bl/'brightness').write_text('512\n');(d/'usr/sbin').mkdir(parents=True);(d/'bin').mkdir()
  (d/'dev').mkdir();(d/'dev/tty1').write_text('')
  if case!='timeout':(d/'run/libra-usb-ready').touch()
  executable(d/'bin/sleep','#!/bin/sh\nexit 0\n')
  executable(d/'usr/sbin/libra-drm-load',r'''#!/bin/sh
echo "$1" >> "$FIXTURE/stages"
if [ "$CASE" = stage_failure ] && [ "$1" = panel ]; then exit 1; fi
if [ "$CASE" = release_failure ] && [ "$1" = release ]; then exit 1; fi
''')
  executable(d/'usr/sbin/libra-drm-test',r'''#!/bin/sh
echo "$1" >> "$FIXTURE/tests"
[ "$CASE" != console_failure ]
''')
  p=d/'bootstrap.sh';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(boot.replace('/sys/',str(d)+'/sys/').replace('/run/',str(d)+'/run/').replace('/proc/',str(d)+'/proc/').replace('/usr/sbin/',str(d)+'/usr/sbin/').replace('/dev/',str(d)+'/dev/'))
  env=dict(os.environ,PATH=str(d/'bin')+':'+os.environ['PATH'],FIXTURE=str(d),CASE=case)
  run=subprocess.run(['sh',str(p)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  assert run.returncode==(0 if case=='ready' else 1),(case,run.stdout)
  assert (bl/'brightness').read_text().strip()==('512' if case=='ready' else '0'),case
  if case=='timeout':assert not (d/'stages').exists(),case
  else:assert (d/'stages').read_text().splitlines()==(['bias','backlight','panel'] if case=='stage_failure' else ['bias','backlight','panel','release'] if case=='release_failure' else ['bias','backlight','panel','release','console']),case
  if case in ('stage_failure','release_failure'):assert not(d/'tests').exists(),case
  elif case!='timeout':assert (d/'tests').read_text().splitlines()==['console'],case
  print('PASS native bootstrap',case)
# Exercise the real stage helper's console parameter and fresh-fault checks.
loader=(ROOT/'scripts/alpine-drm-load.sh').read_text()
with tempfile.TemporaryDirectory(prefix='libra-native-loader-') as temp:
 for case in ('good','unbound','dsi_fault','clock_input_fault','loaded_without_fbdev','firmware_bound','video_done_fault','cmd_dma_fault','panel_shutdown_fault'):
  d=Path(temp)/case;d.mkdir();(d/'proc/sys/kernel').mkdir(parents=True);(d/'proc/cmdline').write_text('libra.drm_native=1\n');(d/'proc/sys/kernel/tainted').write_text('0\n');(d/'sbin').mkdir();(d/'usr/sbin').mkdir(parents=True);(d/'bin').mkdir()
  for module in ('qcom_labibb_regulator','qcom_wled','panel_sharp_libra_rsp61322'):(d/'sys/module'/module).mkdir(parents=True)
  bl=d/'sys/class/backlight/backlight';(bl/'device/driver').mkdir(parents=True);(bl/'brightness').write_text('512\n');(bl/'device/driver/module').symlink_to(d/'sys/module/qcom_wled')
  if case=='firmware_bound':
   device=d/'sys/bus/platform/drivers/simple-framebuffer/3400000.framebuffer';device.mkdir(parents=True);(device/'driver').symlink_to(device.parent)
  if case=='loaded_without_fbdev':
   (d/'sys/module/msm/parameters').mkdir(parents=True);(d/'sys/module/msm/parameters/fbdev').write_text('N\n');(d/'sys/class/drm/card0/device/driver').mkdir(parents=True);(d/'sys/class/drm/card0/device/driver/module').symlink_to(d/'sys/module/msm')
  executable(d/'bin/dmesg','#!/bin/sh\necho harmless\n')
  executable(d/'bin/sleep','#!/bin/sh\nexit 0\n')
  executable(d/'sbin/modprobe',r'''#!/bin/sh
echo "$*" > "$FIXTURE/modprobe-args"
mkdir -p "$FIXTURE/sys/module/msm/parameters"
echo Y > "$FIXTURE/sys/module/msm/parameters/fbdev"
if [ "$CASE" != unbound ]; then mkdir -p "$FIXTURE/sys/class/drm/card0/device/driver"; ln -s "$FIXTURE/sys/module/msm" "$FIXTURE/sys/class/drm/card0/device/driver/module"; fi
[ "$CASE" != dsi_fault ] || echo 'DSI timeout status=0x1'
case "$CASE" in
 video_done_fault) echo 'wait for video done timed out' ;;
 cmd_dma_fault) echo 'cmd dma tx failed, type=0x5, data0=0x28, ret=-110' ;;
 panel_shutdown_fault) echo 'panel shutdown command failed: -110; forcing power-off' ;;
esac
[ "$CASE" != clock_input_fault ] || echo 'pclk0_clk_src: failed to enable DSI RCG input clock: -22'
exit 0
''')
  executable(d/'usr/sbin/libra-kmsg',r'''#!/bin/sh
log=$1; shift
"$@" > "$log" 2>&1; result=$?
cat "$log"
exit "$result"
''')
  p=d/'load.sh';p.parent.mkdir(parents=True, exist_ok=True);p.write_text(loader.replace('/sys/',str(d)+'/sys/').replace('/proc/',str(d)+'/proc/').replace('/run/',str(d)+'/run/').replace('/usr/sbin/',str(d)+'/usr/sbin/').replace('/sbin/modprobe',str(d)+'/sbin/modprobe'))
  env=dict(os.environ,PATH=str(d/'bin')+':'+os.environ['PATH'],FIXTURE=str(d),CASE=case)
  result=subprocess.run(['sh',str(p),'console'],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  assert result.returncode==(0 if case=='good' else 1),(case,result.stdout)
  assert (bl/'brightness').read_text().strip()=='0',case
  if case in ('loaded_without_fbdev','firmware_bound'):assert not(d/'modprobe-args').exists(),case
  else:assert (d/'modprobe-args').read_text().strip()=='msm fbdev=1 mdp5_core_clk_rate=200000000',case
  print('PASS native console loader',case)
