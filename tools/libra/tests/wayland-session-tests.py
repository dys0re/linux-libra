#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise stopping a PAM-scoped desktop without terminating other logins."""
from pathlib import Path
import os,signal,subprocess,tempfile,time

base=Path(__file__).resolve().parents[1]/'debian'
stop=base/'usr/sbin/libra-wayland-exit'
restore=base/'usr/sbin/libra-wayland-return'
with tempfile.TemporaryDirectory() as td:
    root=Path(td);trace=root/'trace'
    mock=root/'loginctl'
    mock.write_text('''#!/bin/sh
case "$1" in
 list-sessions) printf 'c-ssh 1000 libra - 1 user ttyGS0\nc-test 1000 libra seat0 2 user tty8\n' ;;
 show-session) if [ "$2" = c-test ]; then echo "$TEST_LEADER"; else echo 1; fi ;;
 terminate-session) echo "$2" >> "$TRACE" ;;
 *) exit 1 ;;
esac
''');mock.chmod(0o755)
    env=dict(os.environ,PATH=str(root)+':'+os.environ['PATH'],TRACE=str(trace),TEST_LEADER=str(os.getpid()))
    child=subprocess.Popen(['python3','-c','import ctypes,time; ctypes.CDLL(None).prctl(15,b"labwc",0,0,0); time.sleep(30)'])
    try:
        for _ in range(50):
            if Path(f'/proc/{child.pid}/comm').read_text().strip()=='labwc':break
            time.sleep(.01)
        subprocess.run(['sh',str(stop),str(os.getpid())],env=env,check=True)
        assert child.wait(timeout=3)==-signal.SIGTERM
        assert trace.read_text().splitlines()==['c-test']
        trace.unlink()
        subprocess.run(['sh',str(stop),'0'],env=env,check=True)
        assert not trace.exists()
        subprocess.run(['sh',str(stop)],env=env,check=True)
        assert not trace.exists()
        # The compositor can already be gone while its session still has daemons.
        subprocess.run(['sh',str(stop),str(os.getpid())],env=env,check=True)
        assert trace.read_text().splitlines()==['c-test']
    finally:
        if child.poll() is None:child.terminate();child.wait()
    ctl=root/'systemctl'
    ctl.write_text('''#!/bin/sh
case "$1" in
 list-jobs) [ -z "$TEST_JOB" ] || echo "7 libra-wayland.service $TEST_JOB running" ;;
 is-active) [ "$TEST_GRAPHICAL" = yes ] ;;
 --no-block) echo "$*" >> "$TRACE" ;;
 *) exit 1 ;;
esac
''');ctl.chmod(0o755)
    for job,graphical,expected in [('restart','yes',False),('start','yes',False),('stop','yes',True),('','yes',True),('','no',False)]:
        trace.unlink(missing_ok=True)
        subprocess.run(['sh',str(restore)],env=dict(env,TEST_JOB=job,TEST_GRAPHICAL=graphical),check=True)
        assert trace.exists()==expected,(job,graphical)
        if expected:assert trace.read_text().strip()=='--no-block start lightdm.service'
unit=(base/'etc/systemd/system/libra-wayland.service').read_text()
assert 'ExecStop=+/usr/sbin/libra-wayland-exit $MAINPID' in unit
assert 'ExecStartPre=+/usr/bin/busybox chvt 8' in unit
assert 'WantedBy=' not in unit
print('PASS actual Wayland exit: matching compositor terminates, PAM scope cleaned, unrelated SSH login untouched, invalid leader rejected; X11 return skips restart/shutdown')
