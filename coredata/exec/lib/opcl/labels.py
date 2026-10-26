#!/usr/bin/env python3
"""Forward returns and Barra-style residualization."""

import numpy as np
import pandas as pd

from .equ_io import load_equ_day
from .paths import BARRA, PRICE_60


def load_p1m(sid_series: pd.DataFrame, yyyymmdd: str) -> pd.Series:
    """09:35 VWAP from price_60; fallback to equ open."""
    p = PRICE_60 / yyyymmdd[:4] / f'{yyyymmdd}.price_60_record.csv.gz'
    if p.exists():
        px = pd.read_csv(p, compression='gzip')
        if 'sid' in px.columns and 'vwap_0935' in px.columns:
            return px.set_index('sid')['vwap_0935']
    equ = load_equ_day(yyyymmdd)
    if equ.empty:
        return pd.Series(dtype=float)
    if 'sid' in equ.columns:
        return equ.set_index('sid')['open']
    return equ.set_index('underlying_symbol')['open']


def forward_returns(sod: pd.DataFrame, for_date: str) -> pd.DataFrame:
    """rtn_nc, rtn_3nc using close_nxt / p1m - 1."""
    out = sod.copy()
    equ_t = load_equ_day(for_date)
    if equ_t.empty:
        out['rtn_nc'] = np.nan
        out['rtn_3nc'] = np.nan
        return out

    key = 'sid' if 'sid' in equ_t.columns else 'underlying_symbol'
    close = equ_t.set_index(key)['close']
    open_ = equ_t.set_index(key)['open']

    from datetime import datetime, timedelta
    dt = datetime.strptime(for_date, '%Y%m%d')
    nxt1 = (dt + timedelta(days=1)).strftime('%Y%m%d')
    nxt3 = (dt + timedelta(days=3)).strftime('%Y%m%d')
    c1 = load_equ_day(nxt1).set_index(key)['close'] if not load_equ_day(nxt1).empty else pd.Series(dtype=float)
    c3 = load_equ_day(nxt3).set_index(key)['close'] if not load_equ_day(nxt3).empty else pd.Series(dtype=float)

    idx = out[key] if key in out.columns else out.index
    p1m = load_p1m(out, for_date)
    if isinstance(p1m, pd.Series) and key in out.columns:
        denom = out[key].map(p1m)
    else:
        denom = out[key].map(open_) if key in out.columns else open_
    denom = denom.replace(0, np.nan)
    out['p1m'] = denom
    out['close_nxt_1'] = out[key].map(c1) if key in out.columns else np.nan
    out['close_nxt_3'] = out[key].map(c3) if key in out.columns else np.nan
    out['rtn_nc'] = out['close_nxt_1'] / denom - 1
    out['rtn_3nc'] = out['close_nxt_3'] / denom - 1
    return out


def _load_risk_exposures(for_date: str) -> pd.DataFrame | None:
    """
    Production: Lean Barra exposures (built daily).

    Official mk4 is calibration-only; set ``LEAN_BARRA_USE_OFFICIAL=1`` to force it.
    """
    import os

    from ..lean_barra.pipeline import load_exposures

    lean = load_exposures(for_date)
    if not lean.empty and os.environ.get('LEAN_BARRA_USE_OFFICIAL', '').strip() not in ('1', 'true', 'yes'):
        return lean

    p = BARRA / for_date[:4] / f'{for_date}.usfastd_rsk.rev.mk4.csv.gz'
    if p.exists() and os.environ.get('LEAN_BARRA_USE_OFFICIAL', '').strip() in ('1', 'true', 'yes'):
        from ..lean_barra.mk4_loader import load_mk4
        return load_mk4(p)
    return lean if not lean.empty else None


def barra_residualize(df: pd.DataFrame, y_col: str, for_date: str) -> pd.Series:
    """
    Prod-aligned residualization (``ResRtnHelperQbt``):
    simultaneous GLS on ESTU, sqrt(cap) weights, return clip, industry-neutral.
    """
    risk_model = _load_risk_exposures(for_date)
    if risk_model is None:
        return df[y_col]

    from ..lean_barra.residualize import residualize_merged

    return residualize_merged(df, y_col, risk_model)


def add_residual_labels(sod: pd.DataFrame, for_date: str) -> pd.DataFrame:
    out = forward_returns(sod, for_date)
    out['res_rtn_twap_nc'] = barra_residualize(out, 'rtn_nc', for_date)
    out['res_rtn_twap_3nc'] = barra_residualize(out, 'rtn_3nc', for_date)
    return out
