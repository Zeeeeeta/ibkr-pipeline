#!/usr/bin/env python3
"""EXSS backtest: daily L1-normalized portfolio PnL."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.calendar import active_model_date, list_saved_models, list_step2_dates, year_end_trading_dates
from lib.exss.config_exp import CURRENT_EXP_CONFIG
from lib.exss.features import prefetch_training_ratios
from lib.exss.labels import attach_labels
from lib.exss.paths import EXSS_OUT, NO_FILLNA_EXPERIMENT, step2_path
from lib.exss.postprocess import postprocess_alpha
from lib.exss.train_predict import load_model, load_model_meta, predict_raw


def parse_args():
    p = argparse.ArgumentParser(description='EXSS backtest')
    p.add_argument('--start', required=True)
    p.add_argument('--end', required=True)
    p.add_argument('--return-col', default='res_rtn_twap_nc')
    p.add_argument('--output', type=Path, default=None)
    return p.parse_args()


def _portfolio_ret(
    sub: pd.DataFrame,
    alpha: pd.Series,
    ret: pd.Series,
    *,
    long_only: bool = False,
) -> float:
    mask = ret.notna() & alpha.notna()
    if mask.sum() < 2:
        return np.nan
    a = alpha.loc[mask].astype(float)
    r = ret.loc[mask].astype(float)
    if long_only:
        a = a.clip(lower=0)
    gross = a.abs().sum()
    if gross <= 0:
        return np.nan
    return float((a / gross * r).sum())


def sharpe(rets: list[float]) -> float:
    arr = np.array([x for x in rets if np.isfinite(x)])
    if len(arr) < 2:
        return 0.0
    sd = arr.std(ddof=1)
    return float(arr.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0


def main():
    args = parse_args()
    dates = list_step2_dates(args.start, args.end)
    prefetch_training_ratios(dates)
    refit_dates = list_saved_models() or year_end_trading_dates('20160101', args.end)
    rows = []
    daily = []

    for ymd in dates:
        model_date = active_model_date(ymd, refit_dates)
        if model_date is None:
            continue
        try:
            model = load_model(model_date)
        except (FileNotFoundError, ImportError):
            continue
        meta = load_model_meta(model_date)
        feature_cols = meta.get('feature_cols')
        predict = pd.read_parquet(step2_path(ymd))
        raw, frame = predict_raw(model, predict, feature_cols=feature_cols)
        alpha = postprocess_alpha(raw, frame)
        labeled = attach_labels(frame, ymd)
        ret_col = args.return_col
        if ret_col not in labeled.columns:
            ret_col = 'rtn_nc'
        ret = labeled[ret_col] if ret_col in labeled.columns else pd.Series(np.nan, index=labeled.index)
        long_only = CURRENT_EXP_CONFIG['direction'] == 'long_only'
        port = _portfolio_ret(labeled, alpha, ret, long_only=long_only)
        daily.append(port)
        rows.append({
            'quote_ymd': ymd,
            'n_names': int(ret.notna().sum()),
            'port_ret': port,
            'model_date': model_date,
            'cum_pnl': float(np.nansum(daily)),
        })

    if not rows:
        raise SystemExit('No backtest days')

    bt = pd.DataFrame(rows)
    rets = bt['port_ret'].dropna().tolist()
    print('=== EXSS backtest ===')
    print(f"Period: {bt['quote_ymd'].iloc[0]} -> {bt['quote_ymd'].iloc[-1]}")
    print(f"  days: {len(bt)}")
    print(f"  hit_rate: {(bt.port_ret > 0).mean():.3f}")
    print(f"  mean_daily: {np.nanmean(rets):.6f}")
    print(f"  sharpe_252: {sharpe(rets):.3f}")
    print(f"  total_pnl: {bt.port_ret.fillna(0).sum():.6f}")

    suffix = '_finra_nyse_no_fillna' if NO_FILLNA_EXPERIMENT else ''
    out = args.output or EXSS_OUT / f'backtest_{args.start}_{args.end}{suffix}.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    bt.to_csv(out, index=False)
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
