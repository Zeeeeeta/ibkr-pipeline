#!/usr/bin/env python3
"""OPCL backtest: daily PnL, Sharpe, cumulative return."""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.opcl.calendar import (
    DEFAULT_TRAIN_YEARS,
    list_feature_dates,
    opcl_trading_days,
    quarter_last_trading_dates,
    training_window_dates,
)
from lib.opcl.features import feature_columns, load_feature_stack, load_features
from lib.opcl.paths import FEATURES_OUT
from lib.opcl.train_predict import fit_model, predict_with_model


def parse_args():
    p = argparse.ArgumentParser(description='OPCL backtest')
    p.add_argument('--start', required=True, help='First predict date YYYYMMDD')
    p.add_argument('--end', required=True, help='Last predict date YYYYMMDD')
    p.add_argument(
        '--mode',
        choices=('quarterly', 'daily'),
        default='quarterly',
        help='quarterly=prod frozen model between quarter-end refits',
    )
    p.add_argument(
        '--train-years',
        type=float,
        default=DEFAULT_TRAIN_YEARS,
        help='Training window for quarterly refit (prod default 9)',
    )
    p.add_argument('--train-days', type=int, default=60,
                   help='Rolling window for daily mode only')
    p.add_argument('--min-train-days', type=int, default=20,
                   help='Min feature files before first prediction (daily mode)')
    p.add_argument('--bucket', default='_all', help='agg_bucket for portfolio')
    p.add_argument('--return-col', default='res_rtn_twap_nc',
                   help='Realized return column (fallback rtn_nc)')
    p.add_argument('--output', type=Path, default=None)
    return p.parse_args()


def realized_return(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        y = df[col]
    else:
        y = pd.Series(np.nan, index=df.index)
    if 'rtn_nc' in df.columns:
        y = y.fillna(df['rtn_nc'])
    return y


def daily_portfolio_return(sub: pd.DataFrame, alpha: pd.Series, ret: pd.Series) -> float:
    """Dollar-neutral weights: w_i = alpha_i / sum(|alpha|)."""
    mask = ret.notna() & alpha.notna()
    if mask.sum() < 2:
        return np.nan
    a = alpha.loc[mask].astype(float)
    r = ret.loc[mask].astype(float)
    gross = a.abs().sum()
    if gross <= 0:
        return np.nan
    w = a / gross
    return float((w * r).sum())


def sharpe_ratio(daily_rets: list, annualization: float = 252.0) -> float:
    arr = np.array([x for x in daily_rets if not np.isnan(x)])
    if len(arr) < 2:
        return 0.0
    mu = arr.mean()
    sd = arr.std(ddof=1)
    if sd <= 0:
        return 0.0
    return float(mu / sd * math.sqrt(annualization))


def _filter_bucket(predict: pd.DataFrame, args) -> pd.DataFrame:
    sub = predict.loc[predict.get('agg_bucket', '_all') == args.bucket].copy()
    if 'prediction_valid_sample' in sub.columns:
        filt = sub.loc[sub['prediction_valid_sample']]
        if len(filt) >= 3:
            sub = filt
        elif 'valid_sample' in sub.columns:
            sub = sub.loc[sub['valid_sample']]
    elif 'valid_sample' in sub.columns:
        sub = sub.loc[sub['valid_sample']]
    return sub if not sub.empty else None


def _portfolio_row(for_date, predict: pd.DataFrame, args) -> dict | None:
    sub = _filter_bucket(predict, args)
    if sub is None:
        return None
    ret = realized_return(sub, args.return_col)
    port_ret = daily_portfolio_return(sub, sub['alpha'], ret)
    return {
        'quote_ymd': for_date,
        'n_names': int(ret.notna().sum()),
        'port_ret': port_ret,
    }


def _bootstrap_quarterly_model(dates, quarter_ends, args):
    """Fit frozen model from the latest quarter-end before the backtest start."""
    prior = [d for d in quarter_ends if d < dates[0]]
    if not prior:
        return None, None, None
    refit_date = max(prior)
    hist_start = str(int(refit_date[:4]) - int(args.train_years) - 1) + refit_date[4:]
    trading_days = opcl_trading_days(hist_start, refit_date)
    available = list_feature_dates(hist_start, refit_date)
    train_dates = training_window_dates(
        trading_days, refit_date, train_years=args.train_years, available=available,
    )
    train = load_feature_stack(train_dates)
    if train.empty:
        return None, None, None
    train = train.loc[train['quote_ymd'] < refit_date].copy()
    feat_cols = feature_columns(train)
    if not feat_cols or train.empty:
        return None, None, None
    return fit_model(train, feat_cols), feat_cols, refit_date


def _refit_on_date(for_date: str, args, hist_start: str):
    td = opcl_trading_days(hist_start, for_date)
    available = list_feature_dates(hist_start, for_date)
    train_dates = training_window_dates(
        td, for_date, train_years=args.train_years, available=available,
    )
    train = load_feature_stack(train_dates)
    if train.empty:
        return None, None, None
    train = train.loc[train['quote_ymd'] < for_date].copy()
    feat_cols = feature_columns(train)
    if train.empty or not feat_cols:
        return None, None, None
    return fit_model(train, feat_cols), feat_cols, for_date


def run_backtest_quarterly(dates, args):
    hist_start = str(int(args.start[:4]) - int(args.train_years) - 1) + '0101'
    quarter_ends = set(quarter_last_trading_dates(opcl_trading_days('19900101', args.end)))

    model, feat_cols, refit_date = _bootstrap_quarterly_model(dates, sorted(quarter_ends), args)
    rows = []
    daily_rets = []

    for for_date in dates:
        if for_date in quarter_ends:
            model, feat_cols, refit_date = _refit_on_date(for_date, args, hist_start)
            if model is None:
                continue

        if model is None:
            model, feat_cols, refit_date = _refit_on_date(for_date, args, hist_start)
            if model is None:
                continue

        predict = load_features(for_date)
        if predict.empty:
            continue
        predict = predict.copy()
        predict['alpha'] = predict_with_model(model, predict, feat_cols).values
        row = _portfolio_row(for_date, predict, args)
        if row is None:
            continue
        daily_rets.append(row['port_ret'])
        row['refit_date'] = refit_date
        row['cum_pnl'] = float(np.nansum(daily_rets))
        rows.append(row)

    return rows


def run_backtest_daily(dates, args):
    rows = []
    daily_rets = []

    for i, for_date in enumerate(dates):
        if i < args.min_train_days:
            continue
        hist_dates = [d for d in dates if d < for_date][-args.train_days:]
        train = load_feature_stack(hist_dates)
        predict = load_features(for_date)
        if predict.empty or train.empty:
            continue
        feat_cols = feature_columns(train)
        if not feat_cols:
            continue
        try:
            from lib.opcl.train_predict import fit_predict
            alpha = fit_predict(train, predict, feat_cols)
        except ValueError:
            continue
        predict['alpha'] = alpha.values
        row = _portfolio_row(for_date, predict, args)
        if row is None:
            continue
        daily_rets.append(row['port_ret'])
        row['refit_date'] = for_date
        row['cum_pnl'] = float(np.nansum(daily_rets))
        rows.append(row)

    return rows


def run_backtest(args):
    dates = list_feature_dates(args.start, args.end)
    if not dates:
        raise SystemExit('No feature dates in range')

    if args.mode == 'quarterly':
        rows = run_backtest_quarterly(dates, args)
    else:
        if len(dates) < args.min_train_days + 1:
            raise SystemExit(f'Need >= {args.min_train_days + 1} feature dates; have {len(dates)}')
        rows = run_backtest_daily(dates, args)

    if not rows:
        raise SystemExit('No backtest days produced')

    bt = pd.DataFrame(rows)
    bt['cum_pnl'] = bt['port_ret'].fillna(0).cumsum()
    rets = bt['port_ret'].dropna().tolist()
    stats = {
        'mode': args.mode,
        'days': len(bt),
        'hit_rate': float((bt['port_ret'] > 0).mean()),
        'mean_daily_ret': float(np.nanmean(rets)),
        'std_daily_ret': float(np.nanstd(rets, ddof=1)) if len(rets) > 1 else 0.0,
        'total_pnl': float(bt['port_ret'].fillna(0).sum()),
        'sharpe_252': sharpe_ratio(rets),
        'avg_names': float(bt['n_names'].mean()),
        'n_refits': int(bt['refit_date'].nunique()) if 'refit_date' in bt.columns else 0,
    }

    print('=== OPCL backtest ===')
    print(f"Period: {bt['quote_ymd'].iloc[0]} -> {bt['quote_ymd'].iloc[-1]}  bucket={args.bucket}")
    for k, v in stats.items():
        if isinstance(v, float):
            print(f'  {k}: {v:.6f}')
        else:
            print(f'  {k}: {v}')

    out = args.output or (
        FEATURES_OUT / args.end[:4] / f'backtest_{args.mode}_{args.start}_{args.end}.csv'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    bt.to_csv(out, index=False)
    print(f'Wrote {out}')
    return bt, stats


def main():
    run_backtest(parse_args())


if __name__ == '__main__':
    main()
