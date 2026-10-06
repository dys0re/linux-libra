#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the Libra display callback and boot-helper regressions."""
from pathlib import Path
import subprocess
import sys

for test in sorted(Path(__file__).parent.glob('*-tests.py')):
    print(f'Running {test.name}', flush=True)
    subprocess.run([sys.executable, str(test)], check=True)
