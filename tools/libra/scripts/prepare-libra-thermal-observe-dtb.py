#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive a manual sensor-observation DTB without CPU/CCI DVFS probes."""
import argparse
from pathlib import Path
import shutil
import subprocess

workspace = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--voltages", action="store_true", help="expose manual read-only calibration/SAW probing")
parser.add_argument("--clocks", action="store_true", help="expose manual read-only cluster/CCI probing")
args = parser.parse_args()
if args.voltages:
    args.clocks = True
source = workspace / "build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb"
target = workspace / ("build/libra-voltage-observe.dtb" if args.voltages else ("build/libra-clock-observe.dtb" if args.clocks else "build/libra-thermal-observe.dtb"))
shutil.copyfile(source, target)
aux = subprocess.check_output(["fdtget", "-tx", str(source), "/clock-controller", "phandle"], text=True).strip()
for cpu in (0, 1, 2, 3, 0x100, 0x101):
    subprocess.run(["fdtput", "-tx", str(target), f"/cpus/cpu@{cpu:x}", "clocks", aux], check=True)
for node in ("/soc/clock-controller@f9015000", "/cpufreq@f9019000"):
    status = "okay" if args.voltages or (args.clocks and node == "/soc/clock-controller@f9015000") else "disabled"
    subprocess.run(["fdtput", "-ts", str(target), node, "status", status], check=True)
if args.clocks:
    # Platform probing would otherwise power the domain before the driver gate.
    subprocess.run(["fdtput", "-d", str(target), "/soc/clock-controller@f9015000", "power-domains"], check=True)
if args.voltages:
    subprocess.run(["fdtput", "-d", str(target), "/cpufreq@f9019000", "power-domains"], check=True)
print(target)
