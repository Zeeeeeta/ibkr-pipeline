#!/usr/bin/env python3
"""Compare Lean Barra residuals vs prod ``res_rtn_*`` columns."""

import argparse
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

import numpy as np
import pandas as pd

from lib.lean_barra.mk4_loader import load_mk4
from lib.lean_barra.prod_data import load_prod_returns, tid_ticker_map_from_mk4
from lib.lean_barra.residualize import residualize_returns
from lib.opcl.paths import BARRA


def parse_args():
    p = argparse.ArgumentParser(description='Validate res_rtn vs prod')
    p.add_argument('--for-date', required=True)
    p.add_argument('--tickers', default='PLD,AKR,ACM,AAPL')
    p.add_argument('--prod-data-dir', type=Path, default=Path.home() / "Downloads")
    p.add_argument('--return-col', default='rtn_t_nc', help='Raw return column in prod parquet')
    p.add_argument('--res-col', default='res_rtn_t_nc', help='Prod residual column')
    p.add_argument('--tod-hour', type=int, default=16)
    return p.parse_args()


def main():
    args = parse_args()
    tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]

    mk4_path = BARRA / args.for_date[:4] / f'{args.for_date}.usfastd_rsk.rev.mk4.csv.gz'
    if not mk4_path.exists():
        print(f'Missing mk4: {mk4_path}')
        sys.exit(1)

    risk = load_mk4(mk4_path)
    tid_map = tid_ticker_map_from_mk4(args.for_date)
    prod = load_prod_returns(
        args.for_date, root=args.prod_data_dir, tod_hour=args.tod_hour, tid_map=tid_map,
    )

    merged = prod.merge(risk, on='tid', how='inner', suffixes=('', '_barra'))
    if args.return_col not in merged.columns:
        print(f'Missing {args.return_col} in prod data')
        sys.exit(1)

    risk_sub = risk.set_index('tid').reindex(merged['tid'].values).reset_index(drop=True)
    risk_sub.index = merged.index
    y = merged[args.return_col].astype(float)
    lean_res = residualize_returns(y, risk_sub)
    merged['lean_res'] = lean_res.values
    merged['prod_res'] = merged[args.res_col].astype(float)
    merged['res_delta'] = merged['lean_res'] - merged['prod_res']

    sub = merged[merged['symbol'].isin(tickers)] if 'symbol' in merged.columns else merged
    cols = ['symbol', args.return_col, 'prod_res', 'lean_res', 'res_delta']
    cols = [c for c in cols if c in sub.columns]
    print(sub[cols].to_string(index=False))

    valid = sub.dropna(subset=['prod_res', 'lean_res'])
    if len(valid) > 1:
        corr = valid['prod_res'].corr(valid['lean_res'])
        rmse = np.sqrt(((valid['prod_res'] - valid['lean_res']) ** 2).mean())
        print(f'\nCorrelation prod vs lean: {corr:.4f}  RMSE: {rmse:.6f}')


if __name__ == '__main__':
    main()
