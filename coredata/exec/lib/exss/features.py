#!/usr/bin/env python3
"""EXSS model-time feature engineering: filter, EWM-diff, rank, weights."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from .barra_io import load_barra_day
from .config_exp import CURRENT_EXP_CONFIG, ZSCORE_ROLLING_DAYS
from .paths import (
    EXPERIMENT_RATIO_BASES,
    MODEL_FEATURES,
    NO_FILLNA_EXPERIMENT,
    experiment_feature_candidates,
)
from .short_sale_io import load_healthy_ratios
from .step1 import t_minus_1_trading

_RATIO_CACHE: dict[str, pd.DataFrame] = {}
_ZSCORE_PANEL: pd.DataFrame | None = None


def model_feature_candidates() -> list[str]:
    if NO_FILLNA_EXPERIMENT:
        return experiment_feature_candidates()
    return list(MODEL_FEATURES)


def _cached_healthy_ratios(yyyymmdd: str) -> pd.DataFrame:
    if yyyymmdd not in _RATIO_CACHE:
        _RATIO_CACHE[yyyymmdd] = load_healthy_ratios(yyyymmdd)
    return _RATIO_CACHE[yyyymmdd]


def clear_ratio_cache() -> None:
    global _ZSCORE_PANEL
    _RATIO_CACHE.clear()
    _ZSCORE_PANEL = None


def prefetch_training_ratios(train_dates: list[str], *, workers: int = 8) -> None:
    needed: set[str] = set()
    for quote_ymd in train_dates:
        d1 = t_minus_1_trading(str(quote_ymd))
        d2 = t_minus_1_trading(d1)
        needed.add(d1)
        needed.add(d2)
        if CURRENT_EXP_CONFIG['feature_transform'] == 'zscore_20d':
            days = _trailing_trading_days(str(quote_ymd), ZSCORE_ROLLING_DAYS + 1)
            for d in days:
                needed.add(t_minus_1_trading(d))
    if not needed:
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_cached_healthy_ratios, sorted(needed)))
    if CURRENT_EXP_CONFIG['feature_transform'] == 'zscore_20d':
        _build_zscore_panel(train_dates)


def _trailing_trading_days(end_date: str, n: int) -> list[str]:
    from ..opcl.calendar import load_trading_days

    days = load_trading_days('20150101', end_date, feature_fallback=False)
    eligible = [d for d in days if d <= end_date]
    return eligible[-n:]


def _build_zscore_panel(quote_dates: list[str]) -> None:
    """Panel: quote_ymd × symbol × ratio bases (T-1 short sale)."""
    global _ZSCORE_PANEL
    rows: list[pd.DataFrame] = []
    bases = EXPERIMENT_RATIO_BASES
    for qd in sorted(set(str(d) for d in quote_dates)):
        d1 = t_minus_1_trading(qd)
        venues = _cached_healthy_ratios(d1)
        if venues.empty:
            continue
        part = venues[['symbol'] + [c for c in bases if c in venues.columns]].copy()
        part['quote_ymd'] = qd
        rows.append(part)
    if not rows:
        _ZSCORE_PANEL = pd.DataFrame()
        return
    panel = pd.concat(rows, ignore_index=True)
    for base in bases:
        if base in panel.columns:
            panel[base] = pd.to_numeric(panel[base], errors='coerce')
    panel = panel.sort_values(['symbol', 'quote_ymd'])
    for base in bases:
        if base not in panel.columns:
            continue
        zcol = f'{base}_z20'
        panel[zcol] = panel.groupby('symbol', group_keys=False)[base].transform(
            lambda s: _rolling_zscore(s, ZSCORE_ROLLING_DAYS, min_periods=10),
        )
    _ZSCORE_PANEL = panel


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    x = pd.to_numeric(series, errors='coerce')
    mu = x.rolling(window, min_periods=min_periods).mean()
    sd = x.rolling(window, min_periods=min_periods).std()
    return (x - mu) / sd


def _apply_zscore_20d(df: pd.DataFrame, quote_ymd: str, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    if _ZSCORE_PANEL is None or _ZSCORE_PANEL.empty:
        return out
    qd = str(quote_ymd)
    today = _ZSCORE_PANEL.loc[_ZSCORE_PANEL['quote_ymd'] == qd]
    if today.empty:
        return out
    for base in EXPERIMENT_RATIO_BASES:
        zcol = f'{base}_z20'
        if zcol not in today.columns:
            continue
        mapped = today.set_index('symbol')[zcol]
        if base in out.columns:
            out[base] = out['symbol'].map(mapped).combine_first(out[base])
        else:
            out[base] = out['symbol'].map(mapped)
    return out


def enrich_short_sale_ratios(df: pd.DataFrame, quote_ymd: str) -> pd.DataFrame:
    """Overlay FINRA + NYSE FTP ratios from raw files (step1 parquets may be stale)."""
    if not NO_FILLNA_EXPERIMENT:
        return df
    out = df.copy()
    d1 = t_minus_1_trading(str(quote_ymd))
    d2 = t_minus_1_trading(d1)
    for load_d, lag in ((d1, 0), (d2, 1)):
        venues = _cached_healthy_ratios(load_d)
        if venues.empty:
            continue
        sym_map = venues.set_index('symbol')
        for base in EXPERIMENT_RATIO_BASES:
            if base not in sym_map.columns:
                continue
            mapped = out['symbol'].map(sym_map[base])
            if lag == 0:
                if base in out.columns:
                    out[base] = mapped.combine_first(out[base])
                else:
                    out[base] = mapped
            else:
                out[f'{base}_lag1'] = mapped
    return out


def _apply_htb_filter(df: pd.DataFrame, quote_ymd: str) -> pd.DataFrame:
    out = df.copy()
    price_ok = out['close_adj_prv_1'].astype(float) >= 10.0
    barra = load_barra_day(str(quote_ymd))
    cap_col = None
    if not barra.empty:
        for c in ('market_cap', 'capitalization'):
            if c in barra.columns:
                cap_col = c
                break
    if cap_col:
        caps = barra.drop_duplicates('symbol').set_index('symbol')[cap_col]
        out['_mkt_cap'] = out['symbol'].map(caps)
        thresh = out['_mkt_cap'].quantile(0.20)
        cap_ok = out['_mkt_cap'] >= thresh
        mask = price_ok & cap_ok & out['_mkt_cap'].notna()
        out = out.drop(columns=['_mkt_cap'])
    else:
        mask = price_ok
    return out.loc[mask].copy()


def model_filter(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    mask = (
        (out['avg_dollar_volume_21d'] > 10e6)
        & (out['is_stock'] == True)  # noqa: E712
        & out['annualized_var'].notna()
        & out['usfastd_beta'].notna()
    )
    if CURRENT_EXP_CONFIG['direction'] != 'long_only':
        mask = mask & (out['borrow_rate_prev'] < 0.1)
    out = out.loc[mask].copy()
    if CURRENT_EXP_CONFIG['htb_filter'] and 'quote_ymd' in out.columns and len(out):
        qd = str(out['quote_ymd'].iloc[0])
        out = _apply_htb_filter(out, qd)
    return out


def add_ewm_diff_features(df: pd.DataFrame, feature_cols: list[str] | None = None) -> pd.DataFrame:
    out = df.copy()
    feature_cols = feature_cols or model_feature_candidates()
    for feat in feature_cols:
        if not feat.endswith('_1_d'):
            continue
        base = feat.replace('_1_d', '')
        raw_col = base
        ewm_col = f'{base}_1'
        if raw_col in out.columns and ewm_col in out.columns:
            out[feat] = out[ewm_col] - out[raw_col]
        elif raw_col in out.columns and f'{base}_lag1' in out.columns:
            out[feat] = out[raw_col] - out[f'{base}_lag1']
        else:
            out[feat] = np.nan
    return out


def cross_sectional_rank(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if CURRENT_EXP_CONFIG['feature_transform'] == 'zscore_20d':
        return df
    out = df.copy()
    date_key = out.get('quote_ymd', out.get('date'))
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
        ranked = out.groupby(date_key)[c].rank(pct=True)
        if NO_FILLNA_EXPERIMENT:
            out[c] = ranked - 0.5
        else:
            out[c] = ranked.fillna(0.5) - 0.5
            out[c] = out[c].fillna(0.0)
    return out


def sample_weights(df: pd.DataFrame) -> pd.Series:
    adv = df['avg_dollar_volume_21d'].clip(1e6, 10e9)
    ann_var = df['annualized_var'].clip(lower=0.01)
    w = np.sqrt(adv / ann_var / 4e4)
    if not NO_FILLNA_EXPERIMENT:
        w = w.fillna(1.0)
    if w.notna().any() and w.loc[w.notna()].sum() > 0:
        mean_w = w.loc[w.notna()].mean()
        if mean_w and mean_w > 0:
            w = w / mean_w
    return w


def drop_all_nan_features(frame: pd.DataFrame, feature_cols: list[str]) -> list[str]:
    kept = []
    for c in feature_cols:
        if c not in frame.columns:
            continue
        if frame[c].notna().any():
            kept.append(c)
    return kept


def prepare_model_frame(df: pd.DataFrame) -> pd.DataFrame:
    quote_ymd = df['quote_ymd'].iloc[0] if 'quote_ymd' in df.columns and len(df) else None
    out = model_filter(df)
    if quote_ymd is not None:
        out = enrich_short_sale_ratios(out, str(quote_ymd))
    feature_cols = model_feature_candidates()
    if CURRENT_EXP_CONFIG['feature_transform'] == 'zscore_20d' and quote_ymd is not None:
        out = _apply_zscore_20d(out, str(quote_ymd), feature_cols)
    out = add_ewm_diff_features(out, feature_cols)
    out = cross_sectional_rank(out, feature_cols)
    out['sqrt_addv_vol'] = sample_weights(out)
    return out
