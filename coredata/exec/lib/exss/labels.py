#!/usr/bin/env python3
"""Residual return labels for EXSS training."""

from __future__ import annotations

import pandas as pd

from ..opcl.calendar import load_trading_days
from ..opcl.equ_io import load_equ_day
from ..opcl.labels import add_residual_labels, barra_residualize
from .config_exp import CURRENT_EXP_CONFIG
from .paths import NO_FILLNA_EXPERIMENT


def _next_trading_day(for_date: str) -> str | None:
    days = load_trading_days(for_date, '20991231', feature_fallback=False)
    future = [d for d in days if d > for_date]
    return future[0] if future else None


def _attach_open_close_label(df: pd.DataFrame, for_date: str) -> pd.DataFrame:
    """T+1 open-to-close return, Barra-residualized."""
    out = df.copy()
    nxt = _next_trading_day(for_date)
    if nxt is None:
        out['rtn_1d_oc'] = pd.NA
        out['res_rtn_1d_oc'] = pd.NA
        return out

    equ = load_equ_day(nxt)
    if equ.empty or 'open' not in equ.columns or 'close' not in equ.columns:
        out['rtn_1d_oc'] = pd.NA
        out['res_rtn_1d_oc'] = pd.NA
        return out

    key = 'underlying_symbol' if 'underlying_symbol' in equ.columns else 'symbol'
    px = equ.drop_duplicates(key)
    open_ = px.set_index(key)['open'].replace(0, pd.NA)
    close = px.set_index(key)['close']
    rtn = close / open_ - 1.0
    out['rtn_1d_oc'] = out['symbol'].map(rtn)
    out['res_rtn_1d_oc'] = barra_residualize(out, 'rtn_1d_oc', for_date)
    return out


def attach_labels(df: pd.DataFrame, for_date: str) -> pd.DataFrame:
    """Add rtn_nc, rtn_3nc, res_rtn_twap_nc, res_rtn_twap_3nc, res_rtn_1d_oc."""
    base = df.copy()
    if 'underlying_symbol' not in base.columns:
        base['underlying_symbol'] = base['symbol']
    if 'agg_bucket' not in base.columns:
        base['agg_bucket'] = '_all'
    labeled = add_residual_labels(base, for_date)
    return _attach_open_close_label(labeled, for_date)


def training_target(df: pd.DataFrame) -> pd.Series:
    col = CURRENT_EXP_CONFIG['label_window']
    if col not in df.columns:
        raise KeyError(f'Missing label column {col}')
    if NO_FILLNA_EXPERIMENT:
        y = df[col]
    else:
        y = df[col].fillna(df.get('res_rtn_twap_nc'))
    return y.clip(-0.2, 0.25)
