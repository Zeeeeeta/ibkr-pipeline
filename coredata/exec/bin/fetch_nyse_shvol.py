#!/usr/bin/env python3
"""Fetch NYSE-group lit short-sale volume (nyse, nyse_arca) from nyxdata FTP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.lit_shvol_io import (
    fetch_nyxdata_txt,
    load_trading_days_or_weekdays,
    parse_regsho_pipe,
    write_venue_day,
)
from lib.exss.paths import short_sale_path

# ftp.nyxdata.com/ShortData/{PREFIX}/...
VENUE_PREFIXES = {
    'nyse': 'NYSEshvol',
    'nyse_arca': 'ARCAshvol',
}


def parse_args():
    p = argparse.ArgumentParser(description='Fetch NYSE lit short sale volume (2 venues)')
    p.add_argument('--start', required=True, help='YYYYMMDD')
    p.add_argument('--end', required=True, help='YYYYMMDD')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force', action='store_true', help='Overwrite existing files')
    return p.parse_args()


def fetch_day(yyyymmdd: str, *, dry_run: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    for venue, prefix in VENUE_PREFIXES.items():
        raw = fetch_nyxdata_txt(prefix, yyyymmdd)
        if not raw:
            continue
        df = parse_regsho_pipe(raw.decode('utf-8', errors='replace'))
        stats[venue] = write_venue_day(yyyymmdd, venue, df, dry_run=dry_run)
    return stats


def main():
    args = parse_args()
    days = load_trading_days_or_weekdays(args.start, args.end)
    ok = skip = fail = 0
    for ymd in days:
        if short_sale_path(ymd, 'nyse').exists() and not args.force:
            skip += 1
            continue
        try:
            stats = fetch_day(ymd, dry_run=args.dry_run)
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
