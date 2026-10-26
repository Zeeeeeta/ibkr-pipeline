#!/usr/bin/env python3
"""Validate prod short_sale directory layout and report coverage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.paths import ALL_EXCHANGES, SHORT_SALE, short_sale_path
from lib.exss.short_sale_io import venues_present
from lib.opcl.calendar import load_trading_days


def parse_args():
    p = argparse.ArgumentParser(description='Validate / ingest short_sale layout')
    p.add_argument('--start', default='20260101')
    p.add_argument('--end', default='20260409')
    p.add_argument('--source', type=Path, default=None,
                   help='Optional prod source dir to rsync from (manual: rsync -av source/ SHORT_SALE/)')
    return p.parse_args()


def main():
    args = parse_args()
    if args.source:
        print(f'Copy short_sale data manually:')
        print(f'  rsync -av {args.source}/ {SHORT_SALE}/')
        print(f'Then re-run without --source to validate.')

    SHORT_SALE.mkdir(parents=True, exist_ok=True)
    days = load_trading_days(args.start, args.end, feature_fallback=False)
    rows = []
    for ymd in days:
        present = venues_present(ymd)
        rows.append({
            'date': ymd,
            'n_venues': len(present),
            'lit': sum(1 for v in present if not v.startswith('finra_')),
            'finra': sum(1 for v in present if v.startswith('finra_')),
            'missing': ','.join(v for v in ALL_EXCHANGES if v not in present),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        print('No trading days in range')
        sys.exit(1)
    full = (df['n_venues'] == len(ALL_EXCHANGES)).sum()
    print(f'SHORT_SALE root: {SHORT_SALE}')
    print(f'Dates: {len(df)}  full_11_venue: {full}  any_data: {(df.n_venues > 0).sum()}')
    print(f'Avg venues/day: {df.n_venues.mean():.1f}')
    if full == 0:
        print('WARNING: no dates with all 11 venues — lit exchange copy from prod required for full model.')
    print(df.groupby('n_venues').size().to_string())


if __name__ == '__main__':
    main()
