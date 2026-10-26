#!/usr/bin/env python3
"""Stage 2: valid_sample filters, z-scores, cross-sectional ranks."""

import numpy as np
import pandas as pd

from .aggregate import bucket_net_qty, mm_total_qty_row
from .equ_io import adv_21d, load_equ_day

FLOW_ZSCORE_PREFIXES = (
    'firm', 'bd', 'mm', 'cust_lt_100', 'cust_100_199', 'cust_gt_199',
    'procust_lt_100', 'procust_gt_199',
)
REDUCED_SIGNALS = ('total_exchange_vol', 'open_interest', 'put_call_vol_imbalance')


def load_borrow_rate(for_date: str) -> pd.Series:
    from .paths import LOCATES
    for name in (f'{for_date}.locates_us_multi_prime.rev.csv.gz', f'{for_date}.locates.rev.csv.gz'):
        p = LOCATES / for_date[:4] / name
        if p.exists():
            df = pd.read_csv(p, compression='gzip')
            if 'sid' in df.columns and 'fee_rate' in df.columns:
                return df.groupby('sid')['fee_rate'].min()
    return pd.Series(dtype=float)


def add_mm_total_qty(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['mm_total_qty'] = out.apply(mm_total_qty_row, axis=1)
    return out


def zscore_series(s: pd.Series) -> pd.Series:
    m = s.mean()
    sd = s.std()
    if sd == 0 or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - m) / sd


def _all_bucket_base(df: pd.DataFrame) -> pd.DataFrame:
    all_mask = df.get('agg_bucket', '_all') == '_all'
    return df.loc[all_mask].copy() if all_mask.any() else df.copy()


def _broadcast_zscores(out: pd.DataFrame, base: pd.DataFrame, zcols: list) -> pd.DataFrame:
    if 'sid' not in out.columns:
        for zcol in zcols:
            out[zcol] = np.nan
        return out
    for zcol in zcols:
        out[zcol] = base.set_index('sid')[zcol].reindex(out['sid']).values
    return out


def _add_5day_roll(out: pd.DataFrame) -> pd.DataFrame:
    roll_cols = [c for c in out.columns if c.endswith('_qty_zscore') or c.endswith('_signal_zscore')]
    for c in roll_cols:
        out[f'{c.replace("_zscore", "")}_5day'] = out.groupby('sid')[c].transform(
            lambda s: s.rolling(5, min_periods=1).sum()
        )
    return out


def compute_flow_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """8 flow z-scores on underlying-day aggregates (_all bucket)."""
    out = df.copy()
    base = _all_bucket_base(out)

    for prefix in FLOW_ZSCORE_PREFIXES:
        col = f'{prefix}_qty_zscore'
        if prefix == 'mm':
            base[col] = zscore_series(base.apply(
                lambda r: (r.get('mm_buy_qty') or 0) - (r.get('mm_sell_qty') or 0), axis=1
            ))
        else:
            base[col] = zscore_series(base.apply(lambda r: bucket_net_qty(r, prefix), axis=1))

    zcols = [f'{p}_qty_zscore' for p in FLOW_ZSCORE_PREFIXES]
    out = _broadcast_zscores(out, base, zcols)
    return _add_5day_roll(out)


def compute_reduced_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """Price/OI signals for IB-only (no participant flow)."""
    out = df.copy()
    base = _all_bucket_base(out)

    zcols = []
    for signal in REDUCED_SIGNALS:
        zcol = f'{signal}_signal_zscore'
        if signal in base.columns:
            base[zcol] = zscore_series(base[signal].fillna(0))
        else:
            base[zcol] = 0.0
        zcols.append(zcol)

    out = _broadcast_zscores(out, base, zcols)
    return _add_5day_roll(out)


def cross_sectional_rank(df: pd.DataFrame, feature_cols: list) -> pd.DataFrame:
    out = df.copy()
    for c in feature_cols:
        if c not in out.columns:
            continue
        out[c] = out.groupby('quote_ymd')[c].rank(pct=True)
        out[c] = out[c].fillna(0.5)
    return out


def apply_valid_sample(df: pd.DataFrame, for_date: str, *, reduced: bool = False) -> pd.DataFrame:
    out = df.copy()
    equ = load_equ_day(for_date)
    borrow = load_borrow_rate(for_date)

    out['adv_21d'] = out['underlying_symbol'].apply(lambda s: adv_21d(s, for_date))
    if not equ.empty:
        close_map = equ.drop_duplicates('underlying_symbol').set_index('underlying_symbol')['close']
        out['prev_close'] = out['underlying_symbol'].map(close_map)
    else:
        out['prev_close'] = np.nan
    out['borrow_rate'] = out['sid'].map(borrow) if 'sid' in out.columns else 0.0
    out['borrow_rate'] = out['borrow_rate'].fillna(0)

    out['valid_sample'] = (
        (out['adv_21d'] > 10e6)
        & (out['prev_close'] > 5)
        & (out['borrow_rate'] <= 20)
    )
    if not reduced and 'mm_total_qty' in out.columns:
        mm_hist = out.groupby('sid')['mm_total_qty'].transform(
            lambda s: (s.rolling(20, min_periods=1) >= 20).rolling(10, min_periods=1).sum()
        )
        out['valid_sample'] &= mm_hist >= 10
    out['prediction_valid_sample'] = out['valid_sample'] & (out['adv_21d'] > 15e6)
    return out


def feature_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if 'zscore' in c or c.endswith('_5day')]


def run_feature_engineering(sod: pd.DataFrame, for_date: str, *, reduced: bool = False) -> pd.DataFrame:
    sod = sod.copy()
    sod['model_mode'] = 'reduced' if reduced else 'full'
    if reduced:
        sod = compute_reduced_zscores(sod)
    else:
        sod = add_mm_total_qty(sod)
        sod = compute_flow_zscores(sod)
    feat_cols = feature_columns(sod)
    sod = cross_sectional_rank(sod, feat_cols)
    sod = apply_valid_sample(sod, for_date, reduced=reduced)
    return sod
