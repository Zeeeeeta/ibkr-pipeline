#!/usr/bin/env python3
"""EXSS alpha post-processing: clip, Barra neutralize, normalize."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from ..lean_barra.risk_model import OFFICIAL_STYLE_FACTORS
from .paths import alpha_path, model_path

STYLE_NEUT_COLS = list(OFFICIAL_STYLE_FACTORS) + ['usfastd_country']
ALPHA_STD_TARGET = 0.0002


def clip_forecast(raw: pd.Series, by_date: pd.Series) -> pd.Series:
    out = raw.copy()
    for d in by_date.unique():
        mask = by_date == d
        s = out.loc[mask]
        if len(s) < 3:
            continue
        lo, hi = s.quantile(0.01), s.quantile(0.99)
        out.loc[mask] = s.clip(lo, hi)
    return out


def barra_neutralize(
    forecast: pd.Series,
    df: pd.DataFrame,
    weights: pd.Series,
) -> pd.Series:
    """Weighted OLS on 25 style factors; subtract intercept + fitted exposure."""
    out = forecast.copy()
    date_key = df.get('quote_ymd', df.get('date'))
    factor_cols = [c for c in STYLE_NEUT_COLS if c in df.columns]
    if not factor_cols:
        return out - out.groupby(date_key).transform('mean')

    for d in date_key.unique():
        mask = date_key == d
        sub = df.loc[mask]
        y = out.loc[mask].astype(float)
        w = weights.loc[mask].fillna(1.0).values
        X = sub[factor_cols].fillna(0.0).values
        valid = y.notna() & np.isfinite(X).all(axis=1)
        if valid.sum() < len(factor_cols) + 2:
            out.loc[mask] = y - y.mean()
            continue
        reg = LinearRegression(fit_intercept=True)
        reg.fit(X[valid], y.loc[valid], sample_weight=w[valid])
        fitted = reg.predict(X)
        out.loc[mask] = y - fitted
    return out


def normalize_alpha(adjusted: pd.Series, by_date: pd.Series) -> pd.Series:
    out = adjusted.copy()
    for d in by_date.unique():
        mask = by_date == d
        s = out.loc[mask]
        sd = s.std()
        if sd and sd > 0:
            out.loc[mask] = s / sd * ALPHA_STD_TARGET
    return out


def postprocess_alpha(raw: pd.Series, df: pd.DataFrame) -> pd.Series:
    date_key = df.get('quote_ymd', df.get('date'))
    w = df.get('sqrt_addv_vol', pd.Series(1.0, index=df.index))
    clipped = clip_forecast(raw, date_key)
    # ADV filter at predict time
    adv_ok = df['avg_dollar_volume_21d'] > 10e6
    clipped = clipped.where(adv_ok, np.nan)
    neutral = barra_neutralize(clipped, df, w)
    return normalize_alpha(neutral, date_key)


def save_alpha(df: pd.DataFrame, for_date: str, alpha: pd.Series) -> Path:
    out = df[['symbol', 'quote_ymd']].copy() if 'quote_ymd' in df.columns else df[['symbol']].copy()
    out['alpha'] = alpha.values
    path = alpha_path(for_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return path


def save_model_meta(refit_date: str, meta: dict) -> None:
    p = model_path(refit_date)
    meta_path = p.with_suffix('.meta.json')
    meta_path.write_text(json.dumps(meta, indent=2), encoding='utf-8')
