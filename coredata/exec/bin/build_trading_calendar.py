#!/usr/bin/env python3
"""
Build NYSE trading-day calendars for OPCL (one CSV per year).

Preferred source: ``pandas_market_calendars`` (NYSE official schedule).
Legacy fallback: ``nyse_calendar.NYSECalendar`` via IB AAPL daily bars (needs TWS).

Output: ``coredata/data/trading_days/YYYY.trading_days.csv``
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.opcl.calendar import TRADING_DAYS_DIR, quarter_last_trading_dates


def parse_args():
    p = argparse.ArgumentParser(description='Build NYSE trading-day calendar files')
    p.add_argument('--years', type=int, default=9,
                   help='Number of years ending at --end-year (default 9)')
    p.add_argument('--end-year', type=int, default=None,
                   help='Last calendar year (default: current year)')
    p.add_argument('--start-year', type=int, default=None,
                   help='Override --years; build explicit start..end range')
    p.add_argument('--source', choices=('mcal', 'ib'), default='mcal',
                   help='mcal=pandas_market_calendars; ib=IBKR AAPL bars')
    p.add_argument('--validate-quarter-ends', action='store_true', default=True)
    return p.parse_args()


def _year_range(args) -> range:
    end = args.end_year or datetime.now().year
    if args.start_year is not None:
        return range(args.start_year, end + 1)
    start = end - args.years + 1
    return range(start, end + 1)


def build_year_mcal(year: int) -> list[str]:
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar('NYSE')
    sched = nyse.schedule(start_date=f'{year}-01-01', end_date=f'{year}-12-31')
    return sched.index.strftime('%Y%m%d').tolist()


def build_year_ib(year: int) -> list[str]:
    from ib_insync import IB, Stock, util

    from nyse_calendar import NYSECalendar

    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=210)
    try:
        cal = NYSECalendar(ib)
        cal.base_cache_dir = TRADING_DAYS_DIR
        days = cal._sync_year_from_api(year)
        days = [str(d) for d in days if str(d).startswith(str(year))]
        return sorted(days)
    finally:
        ib.disconnect()


def write_year(year: int, days: list[str]) -> Path:
    TRADING_DAYS_DIR.mkdir(parents=True, exist_ok=True)
    out = TRADING_DAYS_DIR / f'{year}.trading_days.csv'
    pd.DataFrame({'trading_day': sorted(days)}).to_csv(out, index=False)
    return out


def main():
    args = parse_args()
    years = list(_year_range(args))
    print(f'Building NYSE calendar years {years[0]}..{years[-1]} source={args.source}')

    all_days: list[str] = []
    for year in years:
        if args.source == 'mcal':
            try:
                days = build_year_mcal(year)
            except ImportError as exc:
                raise SystemExit(
                    'Install pandas_market_calendars: pip install pandas_market_calendars',
                ) from exc
        else:
            days = build_year_ib(year)
        path = write_year(year, days)
        qe = [d for d in quarter_last_trading_dates(days) if d.startswith(str(year))]
        print(f'  {year}: {len(days)} sessions -> {path.name}  quarter_ends={qe}')
        all_days.extend(days)

    if args.validate_quarter_ends:
        qe_all = quarter_last_trading_dates(all_days)
        print('Quarter last trading dates (full range):')
        for d in qe_all:
            print(f'  {d}')

    print(f'Done. Files in {TRADING_DAYS_DIR}')


if __name__ == '__main__':
    main()
