#!/usr/bin/env python3
"""
Stage 3 CLI: refit and predict alpha for for_date.

Prod deployment (default):
  - Refit on quarter last trading day with ~9-year training window
  - Daily predict with frozen model until next quarter refit
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.opcl.calendar import (
    DEFAULT_TRAIN_YEARS,
    active_refit_date,
    list_feature_dates,
    opcl_trading_days,
    quarter_last_trading_dates,
    training_window_dates,
)
from lib.opcl.features import feature_columns, load_feature_stack, load_features
from lib.opcl.paths import FEATURES_OUT
from lib.opcl.train_predict import (
    fit_model,
    latest_saved_refit_date,
    load_model_bundle,
    model_bundle_path,
    predict_with_model,
    save_model_bundle,
)


def parse_args():
    p = argparse.ArgumentParser(description='OPCL train/predict alpha')
    p.add_argument('--for-date', required=True, help='Predict date YYYYMMDD')
    p.add_argument(
        '--mode',
        choices=('quarterly', 'daily'),
        default='quarterly',
        help='quarterly=prod frozen model; daily=legacy walk-forward refit',
    )
    p.add_argument(
        '--train-years',
        type=float,
        default=DEFAULT_TRAIN_YEARS,
        help='Training history for quarterly refit (prod default 9)',
    )
    p.add_argument(
        '--train-days',
        type=int,
        default=None,
        help='Override train window in trading days (daily mode default 60)',
    )
    p.add_argument(
        '--force-refit',
        action='store_true',
        help='Refit on for-date even if not quarter-end (quarterly mode)',
    )
    p.add_argument('--output-col', default='alpha')
    return p.parse_args()


def _history_start(for_date: str, train_years: float) -> str:
    dt = datetime.strptime(for_date, '%Y%m%d')
    start = dt - timedelta(days=int(train_years * 365) + 30)
    return start.strftime('%Y%m%d')


def _daily_train_frames(for_date: str, train_days: int) -> pd.DataFrame:
    end = datetime.strptime(for_date, '%Y%m%d')
    dates = []
    for i in range(train_days + 1):
        ymd = (end - timedelta(days=i)).strftime('%Y%m%d')
        if load_features(ymd).shape[0]:
            dates.append(ymd)
    return load_feature_stack(dates)


def _quarterly_refit(
    for_date: str,
    train_years: float,
    *,
    force: bool = False,
) -> tuple[object, list[str], str]:
    hist_start = _history_start(for_date, train_years)
    trading_days = opcl_trading_days(hist_start, for_date)
    if for_date not in trading_days:
        trading_days = sorted(set(trading_days + [for_date]))
    quarter_ends = set(quarter_last_trading_dates(trading_days))

    if for_date not in quarter_ends and not force:
        raise ValueError(f'{for_date} is not a quarter last trading day')

    available = list_feature_dates(hist_start, for_date)
    train_dates = training_window_dates(
        trading_days, for_date, train_years=train_years, available=available,
    )
    train = load_feature_stack(train_dates)
    if train.empty:
        raise ValueError(f'No training features before {for_date}')
    train = train.loc[train['quote_ymd'] < for_date].copy()
    feat_cols = feature_columns(train)
    if not feat_cols:
        raise SystemExit('No zscore feature columns; run build_sod_features first')

    model = fit_model(train, feat_cols)
    path = save_model_bundle(
        model,
        feat_cols,
        for_date,
        train_years=train_years,
        n_train_days=len(train_dates),
        n_train_rows=len(train),
    )
    print(f'Refit on {for_date}: train_days={len(train_dates)} rows={len(train)} -> {path}')
    return model, feat_cols, for_date


def _quarterly_predict(for_date: str, train_years: float, force_refit: bool) -> pd.Series:
    hist_start = _history_start(for_date, train_years)
    all_days = opcl_trading_days('19900101', for_date)
    quarter_ends = quarter_last_trading_dates(all_days)

    if for_date in set(quarter_ends) or force_refit:
        model, feat_cols, refit_date = _quarterly_refit(
            for_date, train_years, force=force_refit,
        )
    else:
        refit_date = active_refit_date(for_date, quarter_ends)
        if refit_date is None:
            refit_date = latest_saved_refit_date(for_date)
        if refit_date is None:
            raise SystemExit(
                f'No quarter-end refit on or before {for_date}; '
                'run --force-refit once to bootstrap, or refit on quarter last trading day',
            )
        if not model_bundle_path(refit_date).exists():
            calendar_refit = refit_date
            try:
                print(f'Missing frozen model for {calendar_refit}; refitting now')
                model, feat_cols, refit_date = _quarterly_refit(
                    calendar_refit, train_years, force=True,
                )
            except (ValueError, SystemExit) as exc:
                fallback = latest_saved_refit_date(for_date)
                if fallback and model_bundle_path(fallback).exists():
                    refit_date = fallback
                    model, feat_cols, meta = load_model_bundle(refit_date)
                    print(
                        f'Calendar refit {calendar_refit} unavailable ({exc}); '
                        f'using saved model refit={refit_date}',
                    )
                else:
                    raise SystemExit(
                        f'Cannot refit for {for_date}: {exc}. '
                        'Bootstrap with --force-refit on a date with feature history.',
                    ) from exc
        else:
            model, feat_cols, meta = load_model_bundle(refit_date)
            print(
                f'Frozen predict {for_date} using model refit={refit_date} '
                f'backend={meta.get("backend", "?")}',
            )

    predict = load_features(for_date)
    if predict.empty:
        raise SystemExit(f'No features for {for_date}')
    missing = [c for c in feat_cols if c not in predict.columns]
    if missing:
        raise SystemExit(f'Predict frame missing training features: {missing[:5]}')
    return predict_with_model(model, predict, feat_cols)


def main():
    args = parse_args()
    predict = load_features(args.for_date)
    if predict.empty:
        print(f'No features for {args.for_date}')
        sys.exit(1)

    if args.mode == 'daily':
        train_days = args.train_days if args.train_days is not None else 60
        all_df = _daily_train_frames(args.for_date, train_days)
        if all_df.empty:
            print('Need at least 2 feature parquet files')
            sys.exit(1)
        train = all_df.loc[all_df['quote_ymd'] < args.for_date]
        predict_df = all_df.loc[all_df['quote_ymd'] == args.for_date]
        feat_cols = feature_columns(all_df)
        if not feat_cols:
            print('No zscore feature columns; run build_sod_features first')
            sys.exit(1)
        from lib.opcl.train_predict import fit_predict

        alpha = fit_predict(train, predict_df, feat_cols)
        out = predict_df.copy()
    else:
        alpha = _quarterly_predict(args.for_date, args.train_years, args.force_refit)
        out = predict.copy()

    out[args.output_col] = alpha.values
    p = FEATURES_OUT / args.for_date[:4] / f'{args.for_date}.opcl.alpha.parq'
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p, index=False)
    print(f'Wrote {p} n={len(out)} mode={args.mode}')


if __name__ == '__main__':
    main()
