#!/usr/bin/env python3
"""Contract-level mk3 -> underlying-day aggregates (_all, _M1, _E1)."""

import numpy as np
import pandas as pd

from ..cboe_schema import FLOW_COLUMNS

PRICE_OI_COLS = ('total_exchange_vol', 'total_industry_vol', 'open_interest')


def _parse_quote_date(s: pd.Series) -> pd.Series:
    # Prod mk3 uses ISO (2026-02-24); IB writer uses MM/DD/YYYY.
    return pd.to_datetime(s, errors='coerce').dt.strftime('%Y%m%d')


def add_strike_close(df: pd.DataFrame, prev_close: pd.Series) -> pd.DataFrame:
    """ATM flag: strike closest to prev_close per underlying-day."""
    out = df.copy()
    out['prev_close'] = out['underlying_symbol'].map(prev_close)
    out['strike_dist'] = (out['strike_price'] - out['prev_close']).abs()
    out['strike_close'] = 0
    for (_, _), grp in out.groupby(['underlying_symbol', 'quote_date'], dropna=False):
        valid = grp['strike_dist'].notna()
        if not valid.any():
            continue
        idx = grp.loc[valid, 'strike_dist'].idxmin()
        out.loc[idx, 'strike_close'] = 1
    return out.drop(columns=['strike_dist'], errors='ignore')


def add_dte_bucket(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    dte = out['days_to_expire']
    out['dte_bucket'] = ((dte >= 10) & (dte <= 60)).astype(int)
    return out


def _flow_qty_cols():
    return [c for c in FLOW_COLUMNS if c.endswith('_qty')]


def _add_call_put_vol(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'call_put_flag' not in out.columns or 'total_exchange_vol' not in out.columns:
        return out
    cp = out['call_put_flag'].astype(str).str.upper().str[0]
    vol = out['total_exchange_vol'].fillna(0)
    out['call_vol'] = np.where(cp == 'C', vol, 0.0)
    out['put_vol'] = np.where(cp == 'P', vol, 0.0)
    return out


def aggregate_underlying_day(df: pd.DataFrame, prev_close: pd.Series) -> pd.DataFrame:
    """Sum flow qty/vol and price/OI cols to underlying x quote_date for _all, _M1, _E1."""
    if df.empty:
        return pd.DataFrame()
    df = add_strike_close(df, prev_close)
    df = add_dte_bucket(df)
    df['quote_ymd'] = _parse_quote_date(df['quote_date'])
    df = _add_call_put_vol(df)

    qty_cols = [c for c in _flow_qty_cols() if c in df.columns]
    vol_cols = [c for c in FLOW_COLUMNS if c.endswith('_vol') and c in df.columns]
    price_cols = [c for c in PRICE_OI_COLS if c in df.columns]
    cp_cols = [c for c in ('call_vol', 'put_vol') if c in df.columns]
    sum_cols = list(dict.fromkeys(qty_cols + vol_cols + price_cols + cp_cols))

    rows = []
    for label, mask in (
        ('_all', pd.Series(True, index=df.index)),
        ('_M1', df['strike_close'] == 1),
        ('_E1', df['dte_bucket'] == 1),
    ):
        sub = df.loc[mask]
        if sub.empty:
            continue
        if sum_cols:
            g = sub.groupby(['sid', 'underlying_symbol', 'quote_ymd'], dropna=False)[sum_cols].sum(min_count=1)
        else:
            g = sub.groupby(['sid', 'underlying_symbol', 'quote_ymd'], dropna=False).size().to_frame('_n')
            g = g.drop(columns=['_n'])
        g = g.reset_index()
        if 'call_vol' in g.columns and 'put_vol' in g.columns:
            denom = g['call_vol'].fillna(0) + g['put_vol'].fillna(0) + 1.0
            g['put_call_vol_imbalance'] = (g['put_vol'].fillna(0) - g['call_vol'].fillna(0)) / denom
        g['agg_bucket'] = label
        rows.append(g)
    if not rows:
        base = df.groupby(['sid', 'underlying_symbol', 'quote_ymd'], dropna=False).size().reset_index(name='_n')
        base['agg_bucket'] = '_all'
        return base.drop(columns=['_n'])
    return pd.concat(rows, ignore_index=True)


def mm_total_qty_row(row: pd.Series) -> float:
    a = row.get('mm_buy_qty') or 0
    b = row.get('mm_sell_qty') or 0
    if pd.isna(a):
        a = 0
    if pd.isna(b):
        b = 0
    return float(a) + float(b)


def bucket_net_qty(row: pd.Series, prefix: str) -> float:
    """Net qty: (open+close buy) - (open+close sell) for firm/bd style prefixes."""
    buy = 0.0
    sell = 0.0
    for leg in ('open_buy', 'close_buy'):
        for side in ('',):
            col = f'{prefix}_{leg}_qty'
            v = row.get(col, 0)
            buy += 0 if pd.isna(v) else float(v)
    for leg in ('open_sell', 'close_sell'):
        col = f'{prefix}_{leg}_qty'
        v = row.get(col, 0)
        sell += 0 if pd.isna(v) else float(v)
    return buy - sell
