#!/usr/bin/env python3
"""Local substitute for /q/common/exec/lib/BusinessDays."""

import csv
from datetime import datetime, timedelta
from pathlib import Path


def _trading_days_cache_dir():
    repo_root = Path(__file__).resolve().parents[3]
    for candidate in (
        repo_root / 'data' / 'trading_days',
        repo_root / 'coredata' / 'data' / 'trading_days',
    ):
        if candidate.is_dir():
            return candidate
    return None


def _load_cached_trading_days(start, end):
    cache_dir = _trading_days_cache_dir()
    if cache_dir is None:
        return None

    start_dt = datetime.strptime(start, '%Y%m%d')
    end_dt = datetime.strptime(end, '%Y%m%d')
    days = []
    for year in range(start_dt.year, end_dt.year + 1):
        path = cache_dir / f'{year}.trading_days.csv'
        if not path.exists():
            continue
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue
            col = 'trading_day' if 'trading_day' in reader.fieldnames else reader.fieldnames[0]
            for row in reader:
                if row.get(col) is None:
                    continue
                days.append(str(row[col]).strip())

    if not days:
        return None

    start_int, end_int = int(start), int(end)
    return sorted({d for d in days if d.isdigit() and start_int <= int(d) <= end_int})


def _weekdays_between(startdate, enddate):
    """Monday–Friday dates between start and end (inclusive), as YYYYMMDD strings."""
    start_dt = datetime.strptime(startdate, '%Y%m%d')
    end_dt = datetime.strptime(enddate, '%Y%m%d')
    out = []
    d = start_dt
    step = timedelta(days=1)
    while d <= end_dt:
        if d.weekday() < 5:
            out.append(d.strftime('%Y%m%d'))
        d += step
    return out


class BusinessDays(object):

    def getBusinessDays(self, startdate, enddate):
        cached = _load_cached_trading_days(startdate, enddate)
        if cached:
            return cached
        return _weekdays_between(startdate, enddate)
