#!/usr/bin/env python3
"""
Backfill lit-exchange Reg SHO short-sale files for the 9y EXSS window.

Phase 0: optional prod rsync (6 lit venues) when PROD_SHORT_SALE_SRC is set.
Phase 1: NYSE nyxdata FTP (nyse, nyse_arca).
Phase 2: NASDAQ FTP (nasdaq, nasdaq_bx) — bx full; nasdaq FTP stops ~2010.
Phase 3: Cboe FTP (bats, baty, edga, edgx) — free through ~2023-06-30.

Example::

    export PROD_SHORT_SALE_SRC='user@prod:/q/coredata/data/prod/na/3.0/short_sale'
    caffeinate -dimsu nohup python3 backfill_lit_shvol_9y.py \\
        >> coredata/data/ref/lit_shvol_9y_backfill.log 2>&1 &
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_BIN = Path(__file__).resolve().parent
_REPO = _BIN.parents[2]
sys.path.insert(0, str(_BIN.parent))

from lib.exss.paths import LIT_EXCHANGES, short_sale_path
from lib.opcl.calendar import load_trading_days

LOG = _REPO / 'coredata' / 'data' / 'ref' / 'lit_shvol_9y_backfill.log'
PROGRESS = _REPO / 'coredata' / 'data' / 'ref' / 'lit_shvol_9y_progress.csv'

DEFAULT_START = '20170522'
DEFAULT_END = '20260402'


def parse_args():
    p = argparse.ArgumentParser(description='Lit short-sale 9y backfill (8 venues)')
    p.add_argument('--start', default=DEFAULT_START)
    p.add_argument('--end', default=DEFAULT_END)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force', action='store_true')
    p.add_argument('--rsync-source', default=os.environ.get('PROD_SHORT_SALE_SRC', '').strip())
    p.add_argument('--skip-rsync', action='store_true')
    p.add_argument('--skip-nyse', action='store_true')
    p.add_argument('--skip-nasdaq', action='store_true')
    p.add_argument('--skip-cboe', action='store_true')
    return p.parse_args()


def _log(msg: str) -> None:
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def _lit_coverage(start: str, end: str) -> tuple[int, int]:
    days = load_trading_days(start, end, feature_fallback=False)
    have = 0
    for d in days:
        if all(short_sale_path(d, ex).exists() for ex in LIT_EXCHANGES):
            have += 1
    return have, len(days)


def _venue_coverage(start: str, end: str) -> dict[str, int]:
    days = load_trading_days(start, end, feature_fallback=False)
    total = len(days)
    out: dict[str, int] = {}
    for ex in LIT_EXCHANGES:
        out[ex] = sum(1 for d in days if short_sale_path(d, ex).exists())
    out['_total_days'] = total
    return out


def _write_progress(start: str, end: str, phase: str) -> None:
    lit, total = _lit_coverage(start, end)
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    header = 'updated_at,phase,lit_full_days,total_days,start,end\n'
    row = (
        f'{time.strftime("%Y-%m-%dT%H:%M:%S")},{phase},{lit},{total},'
        f'{start},{end}\n'
    )
    if not PROGRESS.exists():
        PROGRESS.write_text(header + row, encoding='utf-8')
    else:
        with PROGRESS.open('a', encoding='utf-8') as fh:
            fh.write(row)


def _run_script(name: str, args: argparse.Namespace, extra: list[str] | None = None) -> None:
    cmd = [
        sys.executable,
        str(_BIN / name),
        '--start', args.start,
        '--end', args.end,
    ]
    if args.force:
        cmd.append('--force')
    if args.dry_run:
        cmd.append('--dry-run')
    if extra:
        cmd.extend(extra)
    _log('>> ' + ' '.join(cmd))
    if args.dry_run:
        return
    subprocess.check_call(cmd, cwd=str(_REPO))


def main():
    args = parse_args()
    lit, total = _lit_coverage(args.start, args.end)
    cov = _venue_coverage(args.start, args.end)
    _log(f'window {args.start}..{args.end} trading_days={total}')
    _log(f'coverage lit_8_venue_full={lit}/{total}')
    for ex in LIT_EXCHANGES:
        _log(f'  {ex}: {cov[ex]}/{cov["_total_days"]}')

    steps: list[tuple[str, list[str] | None]] = []
    if not args.skip_rsync and args.rsync_source:
        steps.append(('rsync_short_sale_lit.py', ['--source', args.rsync_source]))
    elif not args.skip_rsync:
        _log('phase 0: skip rsync (set PROD_SHORT_SALE_SRC or --rsync-source)')

    if not args.skip_nyse:
        steps.append(('fetch_nyse_shvol.py', None))
    if not args.skip_nasdaq:
        steps.append(('fetch_nasdaq_shvol.py', None))
    if not args.skip_cboe:
        steps.append(('fetch_cboe_shvol.py', None))

    for i, (name, extra) in enumerate(steps, 1):
        _log(f'phase {i}/{len(steps)}: {name}')
        _run_script(name, args, extra=extra)
        lit, _ = _lit_coverage(args.start, args.end)
        _log(f'after {name} lit_8_venue_full={lit}/{total}')
        _write_progress(args.start, args.end, name)

    _log('backfill_lit_shvol_9y finished')


if __name__ == '__main__':
    main()
