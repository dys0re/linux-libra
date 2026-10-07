#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Guard the delivered kernel's POSIX file locking and reproduce the old error."""
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
config = (workspace / 'build/libra/.config').read_text()
assert 'CONFIG_FILE_LOCKING=y' in config
symbols = subprocess.check_output(['aarch64-linux-gnu-nm', str(workspace / 'build/libra/vmlinux')], text=True)
assert any(line.endswith(' T fcntl_setlk') for line in symbols.splitlines())
source = (workspace / 'linux/include/linux/filelock.h').read_text()
start = source.index('static inline int fcntl_setlk(', source.index('#else /* !CONFIG_FILE_LOCKING */'))
stub = source[start:source.index('\n}\n', start) + 3]
code = '''#include <assert.h>
#include <errno.h>
#define __user
struct file {int unused;};struct flock {int unused;};
''' + stub + '''
int main(void){assert(fcntl_setlk(0,0,0,0)==-EACCES);return 0;}
'''
path = workspace / 'build/validation/file-locking-old-stub.c'
path.write_text(code)
subprocess.run(['cc','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(path),'-o',str(path.with_suffix(''))],check=True)
subprocess.run([str(path.with_suffix(''))],check=True)
installer = (workspace / 'scripts/install-libra-radio-update.sh').read_text()
assert 'fcntl.lockf' in installer and installer.index('fcntl.lockf') < installer.index('apt-get install')
assert 'bootstrap=1' in installer and 'no packages or radio services were started' in installer
print('PASS delivered kernel includes POSIX lock implementation; old stub reproduces EACCES; installer probes runtime locking and offers package-free bootstrap')
