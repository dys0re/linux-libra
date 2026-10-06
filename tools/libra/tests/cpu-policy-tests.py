#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute real policy initialization with the real generic helper's mask behavior."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
driver = (workspace / 'linux/drivers/cpufreq/qcom-msm8992-cpufreq.c').read_text()
core = (workspace / 'linux/drivers/cpufreq/cpufreq.c').read_text()
start = driver.index('static int msm8992_policy_init(')
policy = driver[start:driver.index('\n}\n', start) + 3]
start = core.index('void cpufreq_generic_init(')
generic = core[start:core.index('\n}\n', start) + 3]
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
struct cpumask {unsigned bits;};struct clk {int id;};
struct cpufreq_frequency_table {unsigned frequency;};
struct cpufreq_policy {unsigned cpu;struct cpumask*cpus;void*driver_data;struct clk*clk;bool dvfs_possible_from_any_cpu;struct cpufreq_frequency_table*freq_table;struct {unsigned transition_latency;}cpuinfo;};
struct msm8992_cpufreq {struct clk*cpu[2];struct cpufreq_frequency_table table[2][16];};
static struct msm8992_cpufreq*msm8992_dvfs;
static void cpumask_clear(struct cpumask*m){m->bits=0;}
static void cpumask_setall(struct cpumask*m){m->bits=~0U;}
static void cpumask_set_cpu(unsigned cpu,struct cpumask*m){m->bits|=1U<<cpu;}
#define for_each_possible_cpu(cpu) for((cpu)=0;(cpu)<6;(cpu)++)
'''
main = r'''
int main(void){struct clk a={0},b={1};struct msm8992_cpufreq d={.cpu={&a,&b}};msm8992_dvfs=&d;
 for(unsigned cpu=0;cpu<6;cpu++){struct cpumask mask={~0U};struct cpufreq_policy p={.cpu=cpu,.cpus=&mask};
 assert(!msm8992_policy_init(&p));unsigned cluster=cpu<4?0:1;
 assert(mask.bits==(cluster?0x30U:0x0fU));assert(p.clk==d.cpu[cluster]&&p.freq_table==d.table[cluster]);
 assert(p.driver_data==&d&&p.dvfs_possible_from_any_cpu&&p.cpuinfo.transition_latency==3000000);
 }
 struct cpumask old={0x0f};struct cpufreq_policy p={.cpus=&old};cpufreq_generic_init(&p,d.table[0],3000000);assert(old.bits==~0U);
 puts("PASS actual policy initializer + generic core helper: former order overwrites cluster mask; corrected order preserves A53 CPUs0-3 and A57 CPUs4-5 with independent clocks/tables for every CPU");}
'''
target = workspace / 'build/validation/cpu-policy.c'
target.write_text(prefix + generic + policy + main)
subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(target), '-o', str(target.with_suffix(''))], check=True)
subprocess.run([str(target.with_suffix(''))], check=True)
