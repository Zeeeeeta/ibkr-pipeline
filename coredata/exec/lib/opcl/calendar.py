#!/usr/bin/env python3
"""NYSE trading-day calendar and quarter-end refit dates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from ..paths import COREDATA_DIR
from .paths import FEATURES_OUT

TRADING_DAYS_DIR = COREDATA_DIR / 'data' / 'trading_days'
TRADING_DAYS_PER_YEAR = 252
DEFAULT_TRAIN_YEARS = 9


def _load_year_trading_days(year: int) -> list[str]:
    for name in (f'{year}.trading_days.csv', f'trading_days_{year}.csv'):
        path = TRADING_DAYS_DIR / name
        if path.exists():
            col = pd.read_csv(path, nrows=0).columns[0]
            days = pd.read_csv(path)[col].astype(str).str.replace('-', '', regex=False)
            return sorted(d for d in days if d.startswith(str(year)))
    return []


def list_feature_dates(start: str, end: str) -> list[str]:
    """Trading/feature dates with a non-empty ``*.opcl.parq`` on disk."""
    out = []
    dt = datetime.strptime(start, '%Y%m%d')
    end_dt = datetime.strptime(end, '%Y%m%d')
    while dt <= end_dt:
        ymd = dt.strftime('%Y%m%d')
        if (FEATURES_OUT / ymd[:4] / f'{ymd}.opcl.parq').exists():
            out.append(ymd)
        dt = datetime.fromordinal(dt.toordinal() + 1)
    return sorted(out)


def load_trading_days(start: str, end: str, *, feature_fallback: bool = True) -> list[str]:
    """Sorted NYSE trading days in ``[start, end]`` (YYYYMMDD)."""
    days: set[str] = set()
    y0, y1 = int(start[:4]), int(end[:4])
    for year in range(y0, y1 + 1):
        days.update(_load_year_trading_days(year))
    out = sorted(d for d in days if start <= d <= end)
    if out:
        return out
    if feature_fallback:
        return list_feature_dates(start, end)
    return []


def quarter_of(ymd: str) -> tuple[int, int]:
    dt = datetime.strptime(ymd, '%Y%m%d')
    return dt.year, (dt.month - 1) // 3 + 1


_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}


def quarter_last_trading_dates(trading_days: list[str]) -> list[str]:
    """
    Last NYSE trading day of each calendar quarter.

    Skips quarters whose calendar is incomplete (no session in the quarter's
    terminal month — e.g. partial-year cache must not invent a Q2 end in April).
    """
    by_yq: dict[tuple[int, int], list[str]] = {}
    for d in trading_days:
        y, q = quarter_of(d)
        by_yq.setdefault((y, q), []).append(d)
    out: list[str] = []
    for (y, q), days in sorted(by_yq.items()):
        end_month = _QUARTER_END_MONTH[q]
        if not any(int(d[4:6]) == end_month for d in days):
            continue
        out.append(max(days))
    return out


def opcl_trading_days(start: str, end: str) -> list[str]:
    """NYSE calendar days union feature parquet dates (for local partial history)."""
    cal = load_trading_days(start, end, feature_fallback=False)
    feats = list_feature_dates(start, end)
    return sorted(set(cal) | set(feats))


def active_refit_date(for_date: str, quarter_ends: list[str]) -> str | None:
    """Latest quarter-end refit date on or before ``for_date``."""
    prior = [d for d in quarter_ends if d <= for_date]
    return max(prior) if prior else None


def training_window_dates(
    trading_days: list[str],
    refit_date: str,
    *,
    train_years: float = DEFAULT_TRAIN_YEARS,
    train_days: int | None = None,
    available: list[str] | None = None,
) -> list[str]:
    """
    Trading days used for training at ``refit_date`` (exclusive of predict day).

    Prod default: ~9 years (~2268 trading days) ending the day before refit.
    """
    if refit_date not in trading_days:
        eligible = [d for d in trading_days if d < refit_date]
    else:
        idx = trading_days.index(refit_date)
        eligible = trading_days[:idx]
    if available is not None:
        avail = set(available)
        eligible = [d for d in eligible if d in avail]
    if train_days is not None:
        return eligible[-train_days:]
    n = max(1, int(train_years * TRADING_DAYS_PER_YEAR))
    return eligible[-n:]
