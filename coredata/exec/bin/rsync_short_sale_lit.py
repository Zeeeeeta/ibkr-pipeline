#!/usr/bin/env python3
"""Rsync missing lit short-sale venue files from prod.

Copies the 6 lit venues that are not fully covered by free exchange FTP:
``nasdaq``, ``nasdaq_bx`` (gaps), ``bats``, ``baty``, ``edga``, ``edgx``.

Set source via ``--source`` or env ``PROD_SHORT_SALE_SRC``, e.g.::

    export PROD_SHORT_SALE_SRC='user@prodhost:/q/coredata/data/prod/na/3.0/short_sale'
    python3 rsync_short_sale_lit.py --start 20170522 --end 20260402

Local mount also works::

    python3 rsync_short_sale_lit.py --source /q/coredata/data/prod/na/3.0/short_sale
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.lit_shvol_io import load_trading_days_or_weekdays
from lib.exss.paths import LIT_EXCHANGES, SHORT_SALE, short_sale_path

DEFAULT_VENUES = ('nasdaq', 'nasdaq_bx', 'bats', 'baty', 'edga', 'edgx')


def parse_args():
    p = argparse.ArgumentParser(description='Rsync lit short_sale files from prod')
    p.add_argument('--start', default='20170522')
    p.add_argument('--end', default='20260402')
    p.add_argument('--source', default=os.environ.get('PROD_SHORT_SALE_SRC', '').strip(),
                   help='Local path or user@host:/path/to/short_sale')
    p.add_argument('--dest', type=Path, default=SHORT_SALE)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--missing-only', action='store_true', default=True,
                   help='Only rsync dates missing any of the 6 lit venues (default)')
    return p.parse_args()


def _missing_days(start: str, end: str, venues: tuple[str, ...]) -> list[str]:
    days = load_trading_days_or_weekdays(start, end)
    out: list[str] = []
    for ymd in days:
        if any(not short_sale_path(ymd, v).exists() for v in venues):
            out.append(ymd)
    return out


def _rsync_patterns(venues: tuple[str, ...]) -> list[str]:
    args = ['--include=*/']
    for v in venues:
        args.append(f'--include=*.{v}_shortsale.rev.csv.gz')
    args.append('--exclude=*')
    return args


def _run_rsync(source: str, dest: Path, years: set[str], *, dry_run: bool) -> None:
    src = source.rstrip('/') + '/'
    dest.mkdir(parents=True, exist_ok=True)
    includes = _rsync_patterns(DEFAULT_VENUES)
    for year in sorted(years):
        cmd = ['rsync', '-av']
        if dry_run:
            cmd.append('--dry-run')
        cmd.extend(includes)
        cmd.extend([f'{src}{year}/', f'{dest}/{year}/'])
        print('>>', ' '.join(cmd), flush=True)
        if not dry_run:
            subprocess.check_call(cmd)


def main():
    args = parse_args()
    if not args.source:
        print('No --source / PROD_SHORT_SALE_SRC; skipping prod rsync')
        sys.exit(0)

    days = _missing_days(args.start, args.end, DEFAULT_VENUES) if args.missing_only else (
        load_trading_days_or_weekdays(args.start, args.end)
    )
    if not days:
        print('No missing lit venue days in range')
        return

    years = {d[:4] for d in days}
    print(f'rsync {len(days)} days across years {sorted(years)} from {args.source}')
    _run_rsync(args.source, args.dest, years, dry_run=args.dry_run)

    still = _missing_days(args.start, args.end, DEFAULT_VENUES)
    print(f'after rsync: missing_days={len(still)}/{len(load_trading_days_or_weekdays(args.start, args.end))}')


if __name__ == '__main__':
    main()
