#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the RPM rate setter with off/on clocks and failing vote writes."""
from pathlib import Path
import subprocess
import tempfile

W = Path(__file__).resolve().parents[4]
s = (W / 'linux/drivers/clk/qcom/clk-smd-rpm.c').read_text()


def fn(name):
    a = s.rfind('\nstatic ', 0, s.index(name + '(')) + 1
    return s[a:s.index('\n}\n', a) + 3]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stddef.h>
struct clk_hw {int x;};
struct clk_smd_rpm { struct clk_hw hw; bool enabled,active_only; unsigned long rate; struct clk_smd_rpm *peer; };
#define to_clk_smd_rpm(p) ((struct clk_smd_rpm*)((char*)(p)-offsetof(struct clk_smd_rpm,hw)))
#define max(a,b) ((a)>(b)?(a):(b))
static int rpm_smd_clk_lock,locked,active_calls,sleep_calls,failure;
static unsigned long active_vote,sleep_vote;
static void mutex_lock(int *p) { (void)p;assert(!locked);locked=1; }
static void mutex_unlock(int *p) { (void)p;assert(locked);locked=0; }
static int clk_smd_rpm_set_rate_active(struct clk_smd_rpm *r,unsigned long rate) { (void)r; assert(locked);active_calls++;active_vote=rate;return failure==1?-EIO:0; }
static int clk_smd_rpm_set_rate_sleep(struct clk_smd_rpm *r,unsigned long rate) { (void)r; assert(locked);sleep_calls++;sleep_vote=rate;return failure==2?-EIO:0; }
'''
main = r'''
int main(void) {
 struct clk_smd_rpm p={0},r={.rate=2147483647,.peer=&p};
 assert(!clk_smd_rpm_set_rate(&r.hw,180000000,0)); assert(r.rate==180000000 && !active_calls && !sleep_calls && !locked);
 r.enabled=true;assert(!clk_smd_rpm_set_rate(&r.hw,300000000,0)); assert(r.rate==300000000 && active_vote==300000000 && sleep_vote==300000000 && !locked);
 p.enabled=true;p.active_only=true;p.rate=384000000;
 assert(!clk_smd_rpm_set_rate(&r.hw,180000000,0));assert(r.rate==180000000 && active_vote==384000000 && sleep_vote==180000000);
 for(failure=1;failure<=2;failure++){r.rate=600000000;assert(clk_smd_rpm_set_rate(&r.hw,300000000,0)==-EIO);assert(r.rate==600000000 && !locked);}
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    c, exe = Path(tmp) / 'rates.c', Path(tmp) / 'rates'
    c.write_text(prefix + fn('to_active_sleep') + fn('clk_smd_rpm_set_rate') + main)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS actual RPM setter: disabled clocks cache requested rate with no writes; active/sleep/peer votes and errors retain correct cached state')
