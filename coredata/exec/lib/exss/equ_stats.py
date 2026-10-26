#!/usr/bin/env python3
"""Equity stats for EXSS filters and sample weights."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..opcl.calendar import load_trading_days
from ..opcl.equ_io import load_equ_day
from ..opcl.paths import equ_prices_path


def _walk_trading_days(end_yyyymmdd: str, n: int) -> list[str]:
    start = str(int(end_yyyymmdd[:4]) - 2) + '0101'
    days = load_trading_days(start, end_yyyymmdd, feature_fallback=False)
    if not days:
        dt = datetime.strptime(end_yyyymmdd, '%Y%m%d')
        days = []
        while len(days) < n + 30:
            if dt.weekday() < 5:
                days.append(dt.strftime('%Y%m%d'))
            dt -= timedelta(days=1)
        days = sorted(days)
    eligible = [d for d in days if d <= end_yyyymmdd]
    return eligible[-n:]


def prev_close_adj(symbols: pd.Series, for_date: str) -> pd.Series:
    dt = datetime.strptime(for_date, '%Y%m%d') - timedelta(days=1)
    for _ in range(10):
        ymd = dt.strftime('%Y%m%d')
        equ = load_equ_day(ymd)
        if not equ.empty and 'underlying_symbol' in equ.columns:
            m = equ.drop_duplicates('underlying_symbol').set_index('underlying_symbol')['close']
            return symbols.map(m)
        dt -= timedelta(days=1)
    return pd.Series(np.nan, index=symbols.index)


def avg_dollar_volume_21d(symbols: pd.Series, for_date: str) -> pd.Series:
    days = _walk_trading_days(for_date, 21)
    acc: dict[str, list[float]] = {s: [] for s in symbols.unique()}
    for ymd in days:
        equ = load_equ_day(ymd)
        if equ.empty:
            continue
        for _, row in equ.iterrows():
            sym = row.get('underlying_symbol') or row.get('symbol')
            if sym not in acc:
                continue
            vol = float(row.get('volume') or 0)
            close = float(row.get('close') or 0)
            acc[sym].append(vol * close)
    out = {s: (float(np.mean(v)) if v else np.nan) for s, v in acc.items()}
    return symbols.map(out)


def annualized_var(symbols: pd.Series, for_date: str, *, window_cal_days: int = 180) -> pd.Series:
    """Variance of daily returns over ~180 calendar days, clipped ±25%, ×252."""
    dt_end = datetime.strptime(for_date, '%Y%m%d')
    dt_start = dt_end - timedelta(days=window_cal_days)
    days = load_trading_days(dt_start.strftime('%Y%m%d'), for_date, feature_fallback=False)
    if not days:
        days = _walk_trading_days(for_date, 126)

    closes: dict[str, pd.Series] = {s: pd.Series(dtype=float) for s in symbols.unique()}
    for ymd in days:
        equ = load_equ_day(ymd)
        if equ.empty:
            continue
        for _, row in equ.iterrows():
            sym = row.get('underlying_symbol') or row.get('symbol')
            if sym in closes:
                closes[sym][ymd] = float(row.get('close') or np.nan)

    out = {}
    for sym, ser in closes.items():
        ser = ser.sort_index().dropna()
        if len(ser) < 5:
            out[sym] = np.nan
            continue
        rets = ser.pct_change().dropna().clip(-0.25, 0.25)
        out[sym] = float(rets.var(ddof=1) * 252) if len(rets) > 1 else np.nan
    return symbols.map(out)


def load_univ_symbols(for_date: str) -> set[str]:
    from ..paths import DEFAULT_UNIVERSE
    if not DEFAULT_UNIVERSE.exists():
        return set()
    df = pd.read_csv(DEFAULT_UNIVERSE)
    col = 'Symbol' if 'Symbol' in df.columns else df.columns[0]
    return set(df[col].astype(str).str.strip().str.upper())
