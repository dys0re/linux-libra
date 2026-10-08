#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate the private Gallium ABI used by Debian's linked EGL loader."""
from pathlib import Path
import subprocess

W=Path(__file__).resolve().parents[4]
version='25.0.7-2+deb13u1'
soname=f'libgallium-{version}.so'
lib=W/'build/libra-mesa/src/gallium/targets/dri'/soname
dynamic=subprocess.check_output(['readelf','-d',str(lib)],text=True)
versions=subprocess.check_output(['readelf','--version-info',str(lib)],text=True)
assert f'Library soname: [{soname}]' in dynamic
assert f'Name: {soname}' in versions
builder=(W/'scripts/build-libra-mesa.py').read_text()
assert f"DEBIAN_VERSION = '{version}'" in builder
assert "(source / 'VERSION').write_text(DEBIAN_VERSION" in builder
assert 'target_version != DEBIAN_VERSION' in builder
helper=(W/'linux/tools/libra/debian/usr/sbin/libra-gpu-test').read_text()
assert 'LD_LIBRARY_PATH=/usr/lib/libra-gpu/dri' in helper
assert '__EGL_VENDOR_LIBRARY_FILENAMES=/usr/lib/libra-gpu/egl-vendor.json' in helper
egl=W/'build/libra-mesa/src/egl/libEGL_mesa.so.0.0.0'
assert f'Shared library: [{soname}]' in subprocess.check_output(['readelf','-d',str(egl)],text=True)
assert 'src/egl/libEGL_mesa.so.0.0.0' in builder
assert '-Dplatforms=x11,wayland' in builder and '-Dglx=dri' in builder
assert '-Dgbm-backends-path=/usr/lib/libra-gpu/dri' in builder
for name,rel in [('GLX','src/glx/libGLX_mesa.so.0.0.0'),('GBM','src/gbm/libgbm.so.1.0.0'),('GBM backend','src/gbm/backends/dri/dri_gbm.so')]:
    assert (W/'build/libra-mesa'/rel).is_file(),name
rootbuild=(W/'scripts/build-debian-rootfs.sh').read_text()
assert 'libgallium-$mesa_abi.so' in rootbuild
assert 'dpkg-query -W' in rootbuild
assert 'libEGL_mesa.so.0.0.0' in rootbuild
assert 'libGLX_mesa.so.0.0.0' in rootbuild and 'dri_gbm.so' in rootbuild
print('PASS paired private EGL/GLX/GBM/Gallium and GBM backend; X11/Wayland compiled; private backend path handles Xorg environment filtering; incompatible source/EGL versions rejected')
