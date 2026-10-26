#!/usr/bin/env python3
"""EXSS annual refit and daily predict."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.calendar import (
    active_model_date,
    list_saved_models,
    list_step2_dates,
    training_dates_before,
    year_end_trading_dates,
)
from lib.exss.paths import step2_path
from lib.exss.postprocess import postprocess_alpha, save_alpha
from lib.exss.train_predict import fit_model, load_model, load_model_meta, predict_raw, save_model


def parse_args():
    p = argparse.ArgumentParser(description='EXSS train/predict')
    p.add_argument('--mode', choices=('refit', 'predict', 'refit-all'), default='predict')
    p.add_argument('--for-date', default=None, help='Predict date YYYYMMDD')
    p.add_argument('--refit-date', default=None, help='Annual refit date YYYYMMDD')
    p.add_argument('--start', default='20160101')
    p.add_argument('--end', default='20260409')
    return p.parse_args()


def _load_step2_stack(dates: list[str]) -> pd.DataFrame:
    frames = []
    for d in dates:
        p = step2_path(d)
        if p.exists():
            frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def refit_one(refit_date: str, start: str) -> str:
    available = list_step2_dates(start, refit_date)
    train_dates = training_dates_before(refit_date, available)
    train = _load_step2_stack(train_dates)
    if train.empty:
        raise SystemExit(f'No training data before {refit_date}')
    model, feature_cols = fit_model(train)
    path = save_model(
        model, refit_date,
        n_train_days=len(train_dates),
        n_train_rows=len(train),
        feature_cols=feature_cols,
    )
    print(f'Refit {refit_date}: days={len(train_dates)} rows={len(train)} features={feature_cols} -> {path}')
    return path


def predict_one(for_date: str, refit_dates: list[str]) -> None:
    model_date = active_model_date(for_date, refit_dates)
    if model_date is None:
        raise SystemExit(f'No model for {for_date} (lag 15d)')
    p = step2_path(for_date)
    if not p.exists():
        raise SystemExit(f'No step2 for {for_date}')
    predict = pd.read_parquet(p)
    model = load_model(model_date)
    meta = load_model_meta(model_date)
    feature_cols = meta.get('feature_cols')
    raw, frame = predict_raw(model, predict, feature_cols=feature_cols)
    alpha = postprocess_alpha(raw, frame)
    out = save_alpha(frame, for_date, alpha)
    print(f'Predict {for_date} model={model_date} n={len(frame)} -> {out}')


def main():
    args = parse_args()
    refit_dates = year_end_trading_dates(args.start, args.end)

    if args.mode == 'refit-all':
        for rd in refit_dates:
            try:
                refit_one(rd, args.start)
            except SystemExit as exc:
                print(f'skip {rd}: {exc}')
        return

    if args.mode == 'refit':
        rd = args.refit_date or refit_dates[-1]
        refit_one(rd, args.start)
        return

    fd = args.for_date or args.end
    predict_one(fd, list_saved_models() or refit_dates)


if __name__ == '__main__':
    main()
