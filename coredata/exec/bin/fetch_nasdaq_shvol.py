#!/usr/bin/env python3
"""Fetch NASDAQ lit short-sale volume (nasdaq, nasdaq_bx) from nasdaqtrader FTP.

Free source: ftp.nasdaqtrader.com/Files/shortsaledata/daily/{nasdaq,bx}/

Note: ``nasdaq`` daily files on FTP currently stop around 2010-07; post-2010
``nasdaq`` requires prod rsync (see rsync_short_sale_lit.py). ``nasdaq_bx`` has
full history through present.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.lit_shvol_io import (
    fetch_nasdaq_lit_txt,
    load_trading_days_or_weekdays,
    parse_regsho_pipe,
    write_venue_day,
)
from lib.exss.paths import short_sale_path

VENUES = ('nasdaq', 'nasdaq_bx')


def parse_args():
    p = argparse.ArgumentParser(description='Fetch NASDAQ lit short sale volume (2 venues)')
    p.add_argument('--start', required=True, help='YYYYMMDD')
    p.add_argument('--end', required=True, help='YYYYMMDD')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force', action='store_true', help='Overwrite existing files')
    return p.parse_args()


def fetch_day(yyyymmdd: str, *, dry_run: bool = False, force: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    for venue in VENUES:
        if short_sale_path(yyyymmdd, venue).exists() and not force:
            continue
        raw = fetch_nasdaq_lit_txt(venue, yyyymmdd)
        if not raw:
            continue
        df = parse_regsho_pipe(raw.decode('utf-8', errors='replace'))
        n = write_venue_day(yyyymmdd, venue, df, dry_run=dry_run)
        if n:
            stats[venue] = n
    return stats


def main():
    args = parse_args()
    days = load_trading_days_or_weekdays(args.start, args.end)
    ok = skip = fail = 0
    for ymd in days:
        if all(short_sale_path(ymd, v).exists() for v in VENUES) and not args.force:
            skip += 1
            continue
        try:
            stats = fetch_day(ymd, dry_run=args.dry_run, force=args.force)
        except Exception as exc:
            print(f'{ymd} error: {exc}')
            fail += 1
            continue
        if stats:
            print(f'{ymd} {stats}')
            ok += 1
        else:
            print(f'{ymd} no data')
    print(f'Done: fetched={ok} skip={skip} fail={fail}')


if __name__ == '__main__':
    main()
