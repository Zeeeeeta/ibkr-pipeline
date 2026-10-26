#!/usr/bin/env python3
"""
Path B: backfill full screener universe equ_prices from IB.

Default: ~9 trading years of daily bars for every symbol in na_exch_screener.

Example::

    # Full backfill (IB Gateway paper port 4002; uses caffeinate by default)
    IB_PORT=4002 python3 backfill_equ_prices.py --end 20260402

    # Resume / batch
    python3 backfill_equ_prices.py --end 20260402 --skip-existing --offset 0 --limit 200
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.ib_connect import DEFAULT_PORT
from lib.paths import DEFAULT_UNIVERSE


def parse_args():
    p = argparse.ArgumentParser(description='Backfill equ_prices for full universe (Path B)')
    p.add_argument('--end', required=True, help='YYYYMMDD anchor (usually latest trade date)')
    p.add_argument('--train-years', type=float, default=9.0, help='Years of history (default 9)')
    p.add_argument('--universe', type=Path, default=DEFAULT_UNIVERSE)
    p.add_argument('--chunk-years', type=int, default=1)
    p.add_argument('--client-id', type=int, default=71)
    p.add_argument('--ib-port', type=int, default=None, help=f'Gateway/TWS port (default IB_PORT env or {DEFAULT_PORT})')
    p.add_argument('--sleep-ms', type=int, default=350)
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--limit', type=int, default=0, help='0 = all symbols')
    p.add_argument('--skip-existing', action='store_true', default=True)
    p.add_argument('--no-skip-existing', action='store_false', dest='skip_existing')
    p.add_argument('--caffeinate', action='store_true', default=True,
                   help='Run under caffeinate -dimsu so Mac does not sleep (default on)')
    p.add_argument('--no-caffeinate', action='store_false', dest='caffeinate')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def main():
    args = parse_args()
    fetch = _BIN / 'fetch_equ_symbols.py'
    cmd = [
        sys.executable,
        str(fetch),
        '--end', args.end,
        '--train-years', str(args.train_years),
        '--universe', str(args.universe),
        '--chunk-years', str(args.chunk_years),
        '--client-id', str(args.client_id),
        '--sleep-ms', str(args.sleep_ms),
        '--offset', str(args.offset),
        '--limit', str(args.limit),
        '--reconnect-every', '200',
    ]
    if args.ib_port is not None:
        cmd.extend(['--ib-port', str(args.ib_port)])
    if args.skip_existing:
        cmd.append('--skip-existing')

    if args.caffeinate:
        if not shutil.which('caffeinate'):
            print('warning: caffeinate not found; running without sleep prevention')
        else:
            cmd = ['caffeinate', '-dimsu', *cmd]

    print(' '.join(cmd))
    if args.dry_run:
        return
    raise SystemExit(subprocess.call(cmd))


if __name__ == '__main__':
    main()
