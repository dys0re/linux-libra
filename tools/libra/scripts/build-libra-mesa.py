#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Cross-build the A418 DRI module against the mounted Debian userspace.

Requires target development packages and host ARM64 C/C++ cross compilers,
bison, flex and pkg-config. Keeps all build work in build/, reuses objects.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

W = Path(__file__).resolve().parent.parent
B = W / 'build'
SHA = '592272df3cf01e85e7db300c449df5061092574d099da275d19e97ef0510f8a6'
DEBIAN_SHA = '7ea51db6f4c6a39d28269975b7f652e37333a283819557c5901cbd3eccee446a'
DEBIAN_VERSION = '25.0.7-2+deb13u1'


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def build(root):
    if not os.path.ismount(root) or not (root / 'etc/debian_version').exists():
        raise RuntimeError('Mount the dedicated Debian F2FS image at rootfs first')
    for tool in ('aarch64-linux-gnu-gcc', 'aarch64-linux-gnu-g++', 'bison', 'flex', 'pkg-config', 'patch'):
        if not shutil.which(tool):
            raise RuntimeError(f'Missing host build tool: {tool}')
    archive = B / 'mesa_25.0.7.orig.tar.xz'
    if not archive.exists():
        run(['curl', '-L', '--fail', '-o', archive,
             'https://mirrors.tuna.tsinghua.edu.cn/debian/pool/main/m/mesa/mesa_25.0.7.orig.tar.xz'])
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA:
        raise RuntimeError('Mesa source archive hash mismatch')
    source = B / 'mesa-25.0.7'
    if not (source / 'meson.build').exists():
        source.mkdir(exist_ok=True)
        run(['tar', '-xf', archive, '-C', source, '--strip-components=1'])
    overlay = B / 'mesa_25.0.7-2+deb13u1.debian.tar.xz'
    if not overlay.exists():
        run(['curl', '-L', '--fail', '-o', overlay,
             'https://mirrors.tuna.tsinghua.edu.cn/debian/pool/main/m/mesa/mesa_25.0.7-2+deb13u1.debian.tar.xz'])
    if hashlib.sha256(overlay.read_bytes()).hexdigest() != DEBIAN_SHA:
        raise RuntimeError('Debian Mesa patch archive hash mismatch')
    marker = source / '.libra-debian-patches-applied'
    if not marker.exists():
        run(['tar', '-xf', overlay, '-C', source])
        patches = source / 'debian/patches'
        for line in (patches / 'series').read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            with (patches / line.split()[0]).open('rb') as f:
                run(['patch', '-p1'], cwd=source, stdin=f)
        marker.write_text(DEBIAN_SHA + '\n')
    elif marker.read_text().strip() != DEBIAN_SHA:
        raise RuntimeError('Existing Mesa tree uses a different Debian patch set')
    target_version = subprocess.check_output(
        ['sudo', '-n', 'chroot', str(root), 'dpkg-query', '-W', '-f=${Version}',
         'libegl-mesa0'], text=True).strip()
    if target_version != DEBIAN_VERSION:
        raise RuntimeError(f'EGL version {target_version} does not match the pinned Debian Mesa sources')
    # Debian rules use the full package version for Gallium's SONAME and
    # default symbol version. EGL links that library directly in Mesa 25.
    (source / 'VERSION').write_text(DEBIAN_VERSION + '\n')
    info = source / 'src/freedreno/common/freedreno_devices.py'
    if 'GPUId(418)' not in info.read_text():
        patch = W / 'linux/tools/libra/patches/mesa-25.0.7-adreno418.patch'
        with patch.open('rb') as f:
            run(['patch', '-p1'], cwd=source, stdin=f)
    venv = B / 'libra-mesa-venv'
    if not (venv / 'bin/meson').exists():
        run(['python3', '-m', 'venv', venv])
        run([venv / 'bin/pip', 'install', 'meson', 'ninja', 'mako', 'pyyaml', 'packaging'])
    env = dict(os.environ, PATH=f'{venv}/bin:' + os.environ['PATH'])
    version = max(int(p.name) for p in (root / 'usr/include/c++').iterdir() if p.name.isdigit())
    gcc = root / f'usr/lib/gcc/aarch64-linux-gnu/{version}'
    lib = root / 'usr/lib/aarch64-linux-gnu'
    compat = B / 'libra-mesa-link-compat'
    compat.mkdir(exist_ok=True)
    # Fedora's GCC16 cross spec names this linker shim. Use Debian's runtime.
    (compat / 'libatomic_asneeded.so').write_text('INPUT ( AS_NEEDED ( -latomic ) )\n')
    # Compiler intrinsics come from the host cross compiler, not target GCC14.
    common = [f'--sysroot={root}', f'-B{lib}/', f'-L{compat}',
              '-isystem', str(root / 'usr/include/aarch64-linux-gnu'),
              '-include', str(root / 'usr/include/limits.h')]
    cpp = common + ['-isystem', str(root / f'usr/include/c++/{version}'),
                    '-isystem', str(root / f'usr/include/aarch64-linux-gnu/c++/{version}'),
                    '-isystem', str(root / f'usr/include/c++/{version}/backward')]
    link = [f'--sysroot={root}', f'-B{lib}/', f'-B{gcc}/', f'-L{compat}',
            f'-L{lib}', f'-L{gcc}', f'-Wl,-rpath-link,{lib}']
    cpp_link = link + ['-Wl,--no-as-needed,-l:libgcc_s.so.1,--as-needed']
    cross = B / 'libra-mesa-cross.ini'
    cross.write_text(f'''[binaries]
c = 'aarch64-linux-gnu-gcc'
cpp = 'aarch64-linux-gnu-g++'
ar = 'aarch64-linux-gnu-ar'
strip = 'aarch64-linux-gnu-strip'
pkg-config = 'pkg-config'
[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'
[properties]
needs_exe_wrapper = true
sys_root = '{root}'
pkg_config_libdir = ['{lib}/pkgconfig', '{root}/usr/share/pkgconfig']
[built-in options]
c_args = {common!r}
cpp_args = {cpp!r}
c_link_args = {link!r}
cpp_link_args = {cpp_link!r}
''')
    output = B / 'libra-mesa'
    options = ['--buildtype=release', '--prefix=/usr', '-Dgallium-drivers=freedreno,softpipe',
               '-Dfreedreno-kmds=msm', '-Dvulkan-drivers=', '-Dplatforms=x11,wayland', '-Dglx=dri',
               '-Degl=enabled', '-Dgbm=enabled', '-Dglvnd=enabled', '-Dllvm=disabled', '-Dgallium-rusticl=false',
               '-Dgbm-backends-path=/usr/lib/libra-gpu/dri',
               '-Dvideo-codecs=', '-Dvalgrind=disabled', '-Dlibunwind=disabled', '-Dbuild-tests=false']
    if (output / 'meson-private/coredata.dat').exists():
        run([venv / 'bin/meson', 'configure', output] +
            [o for o in options if o.startswith('-D')] +
            [f'-D{name}={values!r}' for name, values in
             (('c_args', common), ('cpp_args', cpp), ('c_link_args', link), ('cpp_link_args', cpp_link))], env=env)
    else:
        run([venv / 'bin/meson', 'setup', output, source, '--cross-file', cross] + options, env=env)
    run([venv / 'bin/ninja', '-C', output, '-j' + os.environ.get('JOBS', '10'),
         f'src/gallium/targets/dri/libgallium-{DEBIAN_VERSION}.so',
         'src/egl/libEGL_mesa.so.0.0.0', 'src/glx/libGLX_mesa.so.0.0.0',
         'src/gbm/libgbm.so.1.0.0', 'src/gbm/backends/dri/dri_gbm.so'], env=env)
    print(output / f'src/gallium/targets/dri/libgallium-{DEBIAN_VERSION}.so')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=W / 'rootfs')
    args = parser.parse_args()
    build(args.root.resolve())
