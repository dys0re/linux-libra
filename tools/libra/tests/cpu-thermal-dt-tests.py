#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare temperature policy and bounded frequency plans with the OEM DTB."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
native = workspace / "build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb"
factory = workspace / "build/factory-libra-reference.dtb"

def prop(dtb, node, key, kind="x"):
    value = subprocess.check_output(["fdtget", "-t", kind, str(dtb), node, key], text=True).strip()
    return value if kind == "s" else [int(x, 16) for x in value.split()]

def children(dtb, node):
    return subprocess.check_output(["fdtget", "-l", str(dtb), node], text=True).splitlines()

oem_sensor = "/soc/tsens@fc4a8000"
sensor = "/soc/thermal-sensor@fc4a9000"
regs = prop(factory, oem_sensor, "reg")
assert prop(native, sensor, "reg") == [regs[0] + 0x1000, 0x1000, regs[0], 0x1000]
assert prop(native, sensor, "interrupts")[:2] == prop(factory, oem_sensor, "interrupts")[:2]
assert prop(native, sensor, "#qcom,sensors") == prop(factory, oem_sensor, "qcom,sensors") == [13]
assert prop(native, "/soc/efuse@fc4bc000", "reg") == regs[2:]
assert prop(native, "/soc/efuse@fc4bc000/tsens-calib@d0", "reg") == [0xd0, 12]
assert prop(native, "/soc/efuse@fc4bc000/tsens-backup@1c0", "reg") == [0x1c0, 0x288]
assert prop(native, "/soc/efuse@fc4bc000/tsens-select@464", "reg") == [0x464, 4]
oem_thermal = "/soc/qcom,msm-thermal"
ids = prop(factory, oem_sensor, "qcom,sensor-id")
assert set(n for n in children(native, "/thermal-zones") if n.startswith("tsens")) == {f"tsens{i}-thermal" for i in ids}
for sensor_id in ids:
    zone = f"/thermal-zones/tsens{sensor_id}-thermal"
    assert prop(native, zone, "thermal-sensors")[1:] == [sensor_id]
    assert prop(native, zone, "polling-delay-passive") == prop(factory, oem_thermal, "qcom,poll-ms")
    assert prop(native, zone + "/trips/critical", "temperature") == [prop(factory, oem_thermal, "qcom,therm-reset-temp")[0] * 1000]
    if sensor_id in (7, 9, 10, 13, 14):
        trip = zone + "/trips/passive"
        assert prop(native, trip, "temperature") == [prop(factory, oem_thermal, "qcom,limit-temp")[0] * 1000]
        assert prop(native, trip, "hysteresis") == [prop(factory, oem_thermal, "qcom,temp-hysteresis")[0] * 1000]
        cpus = prop(native, zone + "/cooling-maps/map", "cooling-device")[::3]
        expected = [0, 4] if sensor_id == 7 else [0 if sensor_id in (9, 10) else 4]
        assert cpus == [prop(native, f"/cpus/cpu@{0 if c == 0 else 0x100:x}", "phandle")[0] for c in expected]

clock = "/soc/clock-controller@f9015000"
oem_clock = "/soc/qcom,cpu-clock-8992@f9015000"
oem_regs = prop(factory, oem_clock, "reg")
assert prop(native, clock, "reg") == oem_regs[:4] + oem_regs[6:10] + oem_regs[4:6] + oem_regs[10:12]
assert prop(native, "/cpufreq@f9019000", "compatible", "s") == "qcom,msm8992-cpufreq"
assert prop(native, "/cpufreq@f9019000", "clock-names", "s") == "a53 a57 cci"
saw_phandles = prop(native, "/cpufreq@f9019000", "qcom,saw-regs")
for cluster, address, cpus in ((0, 0xf9065000, (0, 1, 2, 3)), (1, 0xf9013000, (0x100, 0x101))):
    oem_saw = f"/soc/qcom,spm@{address:x}"
    native_saw = f"/soc/syscon@{address:x}"
    assert saw_phandles[cluster] == prop(native, native_saw, "phandle")[0]
    assert prop(native, native_saw, "reg") == prop(factory, oem_saw, "reg")[:2]
    assert prop(factory, oem_saw, "qcom,cpu-vctl-list") == [prop(factory, f"/cpus/cpu@{cpu:x}", "phandle")[0] for cpu in cpus]
    assert prop(native, native_saw, "qcom,saw2-spm-dly") == prop(factory, oem_saw, "qcom,saw2-spm-dly")
    assert prop(factory, oem_saw, "qcom,vctl-port") == [0]
    assert prop(factory, oem_saw, "qcom,vctl-timeout-us") == [50]
assert prop(native, "/cpufreq@f9019000", "nvmem-cell-names", "s") == "cpr-row62 cpr-row137 cpr-row22 cpr-row138 cpr-row139 cpr-row140 cpr-row56 cpr-row57 cpr-row136 speedbin"
assert prop(native, "/soc/efuse@fc4b8000/speedbin@b0", "reg") == [0xb0, 8]
for row in (62, 137, 22, 138, 139, 140, 56, 57, 136):
    assert prop(native, f"/soc/efuse@fc4bc000/cpr-row@{row * 8:x}", "reg") == [row * 8, 8]
for cpu in (0, 1, 2, 3, 0x100, 0x101):
    assert prop(native, f"/cpus/cpu@{cpu:x}", "clocks")[1:] == [0 if cpu < 4 else 1]

config = (workspace / "build/libra/.config").read_text().splitlines()
for name in ("ARM_QCOM_MSM8992_CPUFREQ", "CPU_FREQ_THERMAL", "CPU_FREQ_DEFAULT_GOV_SCHEDUTIL", "QCOM_TSENS", "NVMEM_QCOM_QFPROM"):
    assert f"CONFIG_{name}=y" in config
print("PASS compiled DT matches factory TSENS topology/fuses/policy and full factory-calibrated DVFS wiring and cluster/CCI topology; cpufreq cooling enabled")
