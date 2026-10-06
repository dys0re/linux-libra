#!/usr/bin/env python3
"""Compare compiled touch wiring with the selected factory DTB and TWRP facts."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
native = workspace / "build/libra/arch/arm64/boot/dts/qcom/msm8992-xiaomi-libra.dtb"
factory = workspace / "build/factory-libra-reference.dtb"

def prop(dtb, node, key, kind="x"):
    out = subprocess.check_output(["fdtget", "-t", kind, str(dtb), node, key], text=True).strip()
    return out if kind == "s" else [int(x, 16) for x in out.split()]

touch = "/soc/i2c@f9924000/touchscreen@70"
oem_touch = "/soc/i2c@f9924000/synaptics@70"
assert prop(native, touch, "compatible", "s") == "syna,rmi4-i2c"
assert prop(native, touch, "reg") == prop(factory, oem_touch, "reg") == [0x70]
assert prop(native, touch, "interrupts") == [61, prop(factory, oem_touch, "interrupts")[1] & 0xf]
assert prop(native, touch, "reset-gpios")[1:] == [60, 1]
assert prop(factory, oem_touch, "synaptics,reset-gpio")[1] == 60
assert prop(factory, oem_touch, "synaptics,reset-on-state") == [0]
assert prop(native, touch, "syna,startup-delay-ms") == prop(factory, oem_touch, "synaptics,power-delay-ms")
assert prop(native, touch, "syna,reset-delay-ms") == prop(factory, oem_touch, "synaptics,reset-delay-ms")
assert prop(native, touch + "/rmi4-f12@12", "syna,sensor-type") == [1]
for node, oem, line in (("/regulator-touch-vdd", "/soc/ts_vreg", 110),
                       ("/regulator-touch-vio", "/soc/tp1v8_vreg", 2),
                       ("/regulator-touch-powerdown", "/soc/tpwdn_vreg", 96)):
    assert prop(native, node, "gpio")[1:] == prop(factory, oem, "gpio")[1:] == [line, 0]
    for name in ("regulator-min-microvolt", "regulator-max-microvolt", "startup-delay-us"):
        assert prop(native, node, name) == prop(factory, oem, name)
children = subprocess.check_output(["fdtget", "-l", str(native), "/soc/i2c@f9924000"], text=True)
assert "touchscreen@4a" not in children
config = (workspace / "build/libra/.config").read_text().splitlines()
for name in ("RMI4_CORE", "RMI4_I2C", "RMI4_F12"):
    assert "CONFIG_" + name + "=y" in config
assert "# CONFIG_RMI4_F34 is not set" in config
print("PASS factory touch rails/GPIOs/IRQ/delays; TWRP Synaptics 0x70/F12; built-in driver without firmware reflashing")
