#!/usr/bin/env python3
"""Fetch Cboe lit short-sale volume (bats, baty, edga, edgx) from ftp.cboe.com.

Free EOD volume summaries live under ``*-equities/short-sale/*shvol*.txt.zip``.
Public shvol zips carry real data through **2023-06-01**; later dates return
deprecation notices only. Post-2023-06 requires paid DataShop or prod copy.

EDGA free window is longest: 2017-05-01 .. 2023-06-01.
BZX/BYX/EDGX shvol zips: 2021-01-04 .. 2023-06-01.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.lit_shvol_io import (
    CBOE_VENUE_SPECS,
    cboe_shvol_in_free_window,
    fetch_cboe_shvol_zip,
    is_cboe_deprecation_notice,
    load_trading_days_or_weekdays,
    parse_regsho_pipe,
    unzip_first_text,
    write_venue_day,
)
from lib.exss.paths import short_sale_path

ALL_VENUES = tuple(CBOE_VENUE_SPECS)


def parse_args():
    p = argparse.ArgumentParser(description='Fetch Cboe lit short sale volume (4 venues)')
    p.add_argument('--start', required=True, help='YYYYMMDD')
    p.add_argument('--end', required=True, help='YYYYMMDD')
    p.add_argument(
        '--venues', default=','.join(ALL_VENUES),
        help=f'Comma-separated subset of {",".join(ALL_VENUES)}',
    )
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force', action='store_true', help='Overwrite existing files')
    return p.parse_args()


def _parse_venues(raw: str) -> tuple[str, ...]:
    venues = tuple(v.strip() for v in raw.split(',') if v.strip())
    bad = [v for v in venues if v not in CBOE_VENUE_SPECS]
    if bad:
        raise SystemExit(f'Unknown venues: {bad}; choose from {ALL_VENUES}')
    return venues


def fetch_day(
    yyyymmdd: str,
    venues: tuple[str, ...],
    *,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[dict[str, int], dict[str, str]]:
    """Return (write_stats, notes) where notes values are skip reasons."""
    stats: dict[str, int] = {}
    notes: dict[str, str] = {}
    for venue in venues:
        if short_sale_path(yyyymmdd, venue).exists() and not force:
            notes[venue] = 'exists'
            continue
        if not cboe_shvol_in_free_window(venue, yyyymmdd):
            notes[venue] = 'outside_free_window'
            continue
        raw = fetch_cboe_shvol_zip(venue, yyyymmdd)
        if not raw:
            notes[venue] = 'no_file'
            continue
        text = unzip_first_text(raw)
        if not text:
            notes[venue] = 'bad_zip'
            continue
        if is_cboe_deprecation_notice(text):
            notes[venue] = 'deprecation_notice'
            continue
        df = parse_regsho_pipe(text)
        if df.empty:
            notes[venue] = 'empty_parse'
            continue
        n = write_venue_day(yyyymmdd, venue, df, dry_run=dry_run)
        if n:
            stats[venue] = n
        else:
            notes[venue] = 'empty_write'
    return stats, notes


def main():
    args = parse_args()
    venues = _parse_venues(args.venues)
    days = load_trading_days_or_weekdays(args.start, args.end)
    ok = skip = fail = deprecation = 0
    for ymd in days:
        if all(short_sale_path(ymd, v).exists() for v in venues) and not args.force:
            skip += 1
            continue
        if not any(cboe_shvol_in_free_window(v, ymd) for v in venues):
            skip += 1
            continue
        try:
            stats, notes = fetch_day(ymd, venues, dry_run=args.dry_run, force=args.force)
        except Exception as exc:
            print(f'{ymd} error: {exc}')
            fail += 1
            continue
        if stats:
            print(f'{ymd} {stats}')
            ok += 1
        elif any(n == 'deprecation_notice' for n in notes.values()):
            deprecation += 1
        elif notes:
            pass  # outside window / no file — expected for partial venue ranges
    print(
        f'Done: fetched={ok} skip={skip} deprecation={deprecation} fail={fail} '
        f'venues={",".join(venues)}'
    )


if __name__ == '__main__':
    main()
