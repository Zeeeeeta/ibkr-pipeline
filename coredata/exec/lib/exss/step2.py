#!/usr/bin/env python3
"""EXSS step2: 252-day calendar-day EWM on ratio panel."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from ..opcl.calendar import load_trading_days
from .paths import EWM_HALFLIVES, EWM_LOOKBACK_DAYS, RATIO_BASE_COLS, step1_path, step2_path


def _calendar_span(end_date: str, n_trading: int) -> tuple[list[str], pd.DatetimeIndex]:
    days = load_trading_days('20150101', end_date, feature_fallback=False)
    eligible = [d for d in days if d <= end_date][-n_trading:]
    if not eligible:
        dt = datetime.strptime(end_date, '%Y%m%d')
        eligible = [(dt - timedelta(days=i)).strftime('%Y%m%d') for i in range(n_trading)][::-1]
    cal_start = datetime.strptime(eligible[0], '%Y%m%d')
    cal_end = datetime.strptime(end_date, '%Y%m%d')
    cal_idx = pd.date_range(cal_start, cal_end, freq='D')
    return eligible, cal_idx


def _load_ratio_panel(dates: list[str]) -> pd.DataFrame:
    """Ratio history only — used for calendar EWM."""
    ratio_cols = [c for c in RATIO_BASE_COLS if c.startswith('ratio_') and c != 'ratio_all']
    frames = []
    for ymd in dates:
        p = step1_path(ymd)
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=['symbol', 'quote_ymd'] + ratio_cols)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _ewm_calendar(series: pd.Series, cal_idx: pd.DatetimeIndex, halflife: int) -> pd.Series:
    """EWM with calendar-day halflife (weekends count as decay)."""
    s = series.copy()
    s.index = pd.to_datetime(s.index.astype(str), format='%Y%m%d')
    s = s.reindex(cal_idx)
    return s.ewm(halflife=f'{halflife}D', times=cal_idx).mean()


def build_step2(for_date: str) -> pd.DataFrame:
    dates, cal_idx = _calendar_span(for_date, EWM_LOOKBACK_DAYS)
    s1 = step1_path(for_date)
    if not s1.exists():
        return pd.DataFrame()
    today = pd.read_parquet(s1)

    panel = _load_ratio_panel(dates)
    if panel.empty:
        return pd.DataFrame()

    ratio_cols = [c for c in RATIO_BASE_COLS if c.startswith('ratio_') and c != 'ratio_all']

    for col in ratio_cols:
        if col not in panel.columns:
            continue
        for hl in EWM_HALFLIVES:
            ewm_col = f'{col}_{hl}'
            vals = []
            for sym in today['symbol'].unique():
                sub = panel.loc[panel['symbol'] == sym, ['quote_ymd', col]].dropna()
                if sub.empty:
                    vals.append((sym, pd.NA))
                    continue
                ser = sub.set_index('quote_ymd')[col].sort_index()
                ewm = _ewm_calendar(ser, cal_idx, hl)
                last = ewm.iloc[-1] if len(ewm) else pd.NA
                vals.append((sym, last))
            m = dict(vals)
            today[ewm_col] = today['symbol'].map(m)

    path = step2_path(for_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    today.to_parquet(path, index=False)
    return today


def load_step2(for_date: str) -> pd.DataFrame:
    p = step2_path(for_date)
    if p.exists():
        return pd.read_parquet(p)
    return build_step2(for_date)
