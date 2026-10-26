#!/usr/bin/env python3
"""Fetch FINRA public short-sale volume into prod short_sale layout."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.paths import short_sale_path
from lib.opcl.calendar import load_trading_days

FINRA_CDN = 'https://cdn.finra.org/equity/regsho/daily/{prefix}shvol{date}.txt'

# Prod FINRA venue files <- FINRA CDN prefixes (merge where noted)
VENUE_PREFIXES = {
    'finra_nasdaq': ('FNSQ', 'FNQC'),
    'finra_nyse': ('FNYX',),
    'finra_orf': ('FORF',),
}


def parse_args():
    p = argparse.ArgumentParser(description='Fetch FINRA short sale volume (3 FINRA venues)')
    p.add_argument('--start', required=True, help='YYYYMMDD')
    p.add_argument('--end', required=True, help='YYYYMMDD')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force', action='store_true', help='Overwrite existing files')
    return p.parse_args()


def _fetch_url(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ibkr-exss-fetch/1.0'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


FINRA_COLS = ['Date', 'Symbol', 'ShortVolume', 'ShortExemptVolume', 'TotalVolume', 'Market']


def _parse_finra_text(text: str) -> pd.DataFrame:
    lines = [ln for ln in text.strip().splitlines() if ln and not ln.startswith('Date|')]
    if not lines:
        return pd.DataFrame()
    if lines[-1].split('|')[0].isdigit() and lines[-1].count('|') <= 1:
        lines = lines[:-1]
    if not lines:
        return pd.DataFrame()
    try:
        df = pd.read_csv(StringIO('\n'.join(lines)), sep='|', header=None)
        if df.shape[1] == len(FINRA_COLS):
            df.columns = FINRA_COLS
        else:
            df = pd.read_csv(StringIO('\n'.join(lines)), sep='|')
            df.columns = [c.strip() for c in df.columns]
        return df
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _write_venue(yyyymmdd: str, venue: str, df: pd.DataFrame, *, dry_run: bool) -> int:
    if df.empty:
        return 0
    out = df.groupby('Symbol', as_index=False).agg(
        shortvolume=('ShortVolume', 'sum'),
        totalvolume=('TotalVolume', 'sum'),
    )
    out.columns = ['symbol', 'shortvolume', 'totalvolume']
    path = short_sale_path(yyyymmdd, venue)
    if dry_run:
        print(f'  would write {path} rows={len(out)}')
        return len(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, compression='gzip')
    return len(out)


def fetch_day(yyyymmdd: str, *, dry_run: bool = False) -> dict[str, int]:
    stats: dict[str, int] = {}
    for venue, prefixes in VENUE_PREFIXES.items():
        parts = []
        for prefix in prefixes:
            url = FINRA_CDN.format(prefix=prefix, date=yyyymmdd)
            text = _fetch_url(url)
            if text:
                parts.append(_parse_finra_text(text))
        if parts:
            merged = pd.concat(parts, ignore_index=True)
            stats[venue] = _write_venue(yyyymmdd, venue, merged, dry_run=dry_run)
    return stats


def main():
    args = parse_args()
    days = load_trading_days(args.start, args.end, feature_fallback=False)
    if not days:
        dt = datetime.strptime(args.start, '%Y%m%d')
        end = datetime.strptime(args.end, '%Y%m%d')
        days = []
        while dt <= end:
            if dt.weekday() < 5:
                days.append(dt.strftime('%Y%m%d'))
            dt += timedelta(days=1)

    ok = skip = fail = 0
    for ymd in days:
        if short_sale_path(ymd, 'finra_nasdaq').exists() and not args.force:
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
