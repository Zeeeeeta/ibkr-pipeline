#!/usr/bin/env python3
"""
Stage 1: build_sod_features — mk3 T-1 + joins -> YYYYMMDD.opcl.parq
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.opcl.aggregate import aggregate_underlying_day
from lib.opcl.equ_io import load_equ_day, prev_close_map
from lib.opcl.feature_engineering import run_feature_engineering
from lib.opcl.labels import add_residual_labels
from lib.opcl.mk3_io import has_flow_data, load_options_day, merge_supplements
from lib.opcl.paths import features_path


def parse_args():
    p = argparse.ArgumentParser(description='Build OPCL SOD features for for_date T')
    p.add_argument('--for-date', required=True, help='YYYYMMDD feature date T')
    p.add_argument('--skip-features', action='store_true', help='Only write raw SOD without stage2')
    p.add_argument('--reduced', action='store_true', help='IB-only price/OI features (skip flow z-scores)')
    p.add_argument('--full', action='store_true', help='Force full flow features (requires mk3 flow data)')
    return p.parse_args()


def t_minus_1(yyyymmdd: str) -> str:
    dt = datetime.strptime(yyyymmdd, '%Y%m%d') - timedelta(days=1)
    for _ in range(10):
        ymd = dt.strftime('%Y%m%d')
        if load_options_day(ymd).shape[0]:
            return ymd
        dt -= timedelta(days=1)
    return (datetime.strptime(yyyymmdd, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')


def main():
    args = parse_args()
    for_date = args.for_date
    load_date = t_minus_1(for_date)

    print(f'for_date={for_date} load_date(T-1)={load_date}')
    opts = load_options_day(load_date)
    if opts.empty:
        print(f'No options data for {load_date}')
        sys.exit(1)
    opts = merge_supplements(opts, load_date)
    flow_ok = has_flow_data(opts)
    if args.full and not flow_ok:
        print('No participant flow in options file; cannot use --full')
        sys.exit(1)
    reduced = args.reduced or (not args.full and not flow_ok)

    prev_close = prev_close_map(for_date)
    agg = aggregate_underlying_day(opts, prev_close)
    if agg.empty:
        print('Empty aggregate')
        sys.exit(1)

    agg['quote_ymd'] = for_date
    sod = add_residual_labels(agg, for_date)

    if not args.skip_features:
        sod = run_feature_engineering(sod, for_date, reduced=reduced)
        print(f'model_mode={"reduced" if reduced else "full"}')

    out = features_path(for_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    sod.to_parquet(out, index=False)
    print(f'Wrote {out} rows={len(sod)} cols={len(sod.columns)}')


if __name__ == '__main__':
    main()
