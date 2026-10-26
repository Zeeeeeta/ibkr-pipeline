#!/usr/bin/env python3
"""Run IB probes and refresh JSON artifacts for ib_mimic_matrix.md."""

import json
import subprocess
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
SCHEMAS = _BIN.parent / 'schemas'


def main():
    cmds = [
        [sys.executable, str(_BIN / 'verify_ib_aapl.py')],
        [sys.executable, str(_BIN / 'probe_ib_options_hist.py'), '--client-id', '103'],
        [sys.executable, str(_BIN / 'probe_ib_flow.py'), '--client-id', '104'],
    ]
    ok = True
    for cmd in cmds:
        print('>>', ' '.join(cmd))
        r = subprocess.run(cmd, cwd=str(_BIN))
        if r.returncode != 0:
            ok = False
    print('Probes done; see', SCHEMAS)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
