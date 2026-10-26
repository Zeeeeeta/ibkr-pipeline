#!/usr/bin/env python3
"""
Backfill EXSS short-sale + features for the 9y OPCL/Lean Barra window.

Phase 1: FINRA short-sale CDN fetch (3 venues; lit exchanges still missing locally).
Phase 2: step1 + step2 feature parquets (skip-existing).

Example::

    nohup python3 backfill_exss_9y.py >> coredata/data/ref/exss_9y_backfill.log 2>&1 &
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_BIN = Path(__file__).resolve().parent
_REPO = _BIN.parents[2]
sys.path.insert(0, str(_BIN.parent))

from lib.exss.paths import step2_path
from lib.exss.short_sale_io import venues_present
from lib.opcl.calendar import load_trading_days

LOG = _REPO / 'coredata' / 'data' / 'ref' / 'exss_9y_backfill.log'
PROGRESS = _REPO / 'coredata' / 'data' / 'ref' / 'exss_9y_progress.csv'

# Align with equ prices + Lean Barra batch
DEFAULT_START = '20170522'
DEFAULT_END = '20260402'


def parse_args():
    p = argparse.ArgumentParser(description='EXSS 9y short-sale + feature backfill')
    p.add_argument('--start', default=DEFAULT_START)
    p.add_argument('--end', default=DEFAULT_END)
    p.add_argument('--skip-fetch', action='store_true')
    p.add_argument('--skip-features', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def _log(msg: str) -> None:
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def _run(cmd: list[str], *, dry_run: bool = False) -> None:
    _log('>> ' + ' '.join(cmd))
    if dry_run:
        return
    subprocess.check_call(cmd, cwd=str(_REPO))


def _short_sale_coverage(start: str, end: str) -> tuple[int, int]:
    days = load_trading_days(start, end, feature_fallback=False)
    have = sum(1 for d in days if venues_present(d))
    return have, len(days)


def _feature_coverage(start: str, end: str) -> tuple[int, int]:
    days = load_trading_days(start, end, feature_fallback=False)
    have = sum(1 for d in days if step2_path(d).exists())
    return have, len(days)


def _write_progress(start: str, end: str, phase: str) -> None:
    ss, st = _short_sale_coverage(start, end)
    ft, tt = _feature_coverage(start, end)
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    header = 'updated_at,phase,short_sale_days,feature_days,total_days,start,end\n'
    row = (
        f'{time.strftime("%Y-%m-%dT%H:%M:%S")},{phase},{ss},{ft},{tt},'
        f'{start},{end}\n'
    )
    if not PROGRESS.exists():
        PROGRESS.write_text(header + row, encoding='utf-8')
    else:
        with PROGRESS.open('a', encoding='utf-8') as fh:
            fh.write(row)


def main():
    args = parse_args()
    py = sys.executable
    fetch = _BIN / 'fetch_finra_shvol.py'
    build = _BIN / 'build_exss_features.py'

    ss, total = _short_sale_coverage(args.start, args.end)
    ft, _ = _feature_coverage(args.start, args.end)
    _log(f'window {args.start}..{args.end} trading_days={total}')
    _log(f'coverage short_sale={ss}/{total} step2={ft}/{total}')

    if not args.skip_fetch:
        _log('phase 1: FINRA short-sale fetch')
        _run([py, str(fetch), '--start', args.start, '--end', args.end], dry_run=args.dry_run)
        ss, _ = _short_sale_coverage(args.start, args.end)
        _log(f'after fetch short_sale={ss}/{total}')
        _write_progress(args.start, args.end, 'fetch_done')

    if not args.skip_features:
        _log('phase 2: EXSS step1+step2 build (--skip-existing)')
        _run([
            py, str(build),
            '--start', args.start,
            '--end', args.end,
            '--skip-existing',
        ], dry_run=args.dry_run)
        ft, _ = _feature_coverage(args.start, args.end)
        _log(f'after build step2={ft}/{total}')
        _write_progress(args.start, args.end, 'features_done')

    _log('backfill_exss_9y finished')


if __name__ == '__main__':
    main()
