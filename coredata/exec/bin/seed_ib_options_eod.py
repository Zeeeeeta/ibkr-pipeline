#!/usr/bin/env python3
"""Seed synthetic IB options EOD rows for pipeline testing without TWS."""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.ib_options_writer import append_rows, empty_row_template, read_day
from lib.option_ids import SymbolSidRegistry
from lib.paths import DEFAULT_OUT_ROOT, COREDATA_DIR


DEFAULT_SYMBOLS = (
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM',
    'V', 'UNH', 'XOM', 'LLY', 'AVGO', 'MA', 'COST',
)


def parse_args():
    p = argparse.ArgumentParser(description='Seed ib_options_eod.csv.gz for OPCL dev runs')
    p.add_argument('--date', required=True, help='Quote date YYYYMMDD (T-1 for for_date T)')
    p.add_argument('--symbols', default=','.join(DEFAULT_SYMBOLS))
    p.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument('--append-missing', action='store_true',
                   help='Only add symbols not already in the daily file')
    return p.parse_args()


def _quote_date(ymd: str) -> str:
    return f'{ymd[4:6]}/{ymd[6:8]}/{ymd[:4]}'


def _load_close(symbol: str, ymd: str) -> float:
    p = COREDATA_DIR / 'data' / 'price' / ymd[:4] / f'{ymd}.equ_prices.csv'
    if not p.exists():
        return 100.0
    df = pd.read_csv(p)
    row = df.loc[df['symbol'] == symbol]
    if row.empty:
        return 100.0
    return float(row.iloc[0]['close'])


def _contract_rows(symbol: str, ymd: str, registry: SymbolSidRegistry, seed: int):
    close = _load_close(symbol, ymd)
    sid = registry.sid_for(symbol)
    expiry = (datetime.strptime(ymd, '%Y%m%d') + timedelta(days=45)).strftime('%Y-%m-%d')
    expiry_key = expiry.replace('-', '')
    atm = round(close * 2) / 2
    specs = (
        ('C', atm, 500 + seed * 17, 5000 + seed * 100),
        ('P', atm, 300 + seed * 11, 4200 + seed * 80),
        ('C', atm + 5, 150 + seed * 7, 2100 + seed * 50),
        ('P', atm - 5, 400 + seed * 13, 3800 + seed * 70),
    )
    rows = []
    for i, (right, strike, vol, oi) in enumerate(specs):
        row = empty_row_template()
        optsid = sid * 1000 + i + 1
        row.update({
            'sid': sid,
            'optsid': optsid,
            'con_id': optsid,
            'quote_date': _quote_date(ymd),
            'underlying_symbol': symbol,
            'option_symbol': symbol,
            'expiration_date': expiry,
            'strike_price': strike,
            'call_put_flag': right,
            'days_to_expire': 45,
            'first_trade_price': max(strike * 0.05, 0.5),
            'high_trade_price': max(strike * 0.06, 0.6),
            'low_trade_price': max(strike * 0.04, 0.4),
            'last_trade_price': max(strike * 0.05, 0.5),
            'total_exchange_vol': float(vol),
            'open_interest': float(oi),
        })
        rows.append(row)
    return rows


def main():
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    if args.append_missing:
        existing = read_day(args.date, args.out_root)
        if not existing.empty and 'underlying_symbol' in existing.columns:
            have = set(existing['underlying_symbol'].astype(str).str.upper())
            symbols = [s for s in symbols if s not in have]
        if not symbols:
            print(f'{args.date}: all symbols present')
            return
    registry = SymbolSidRegistry()
    all_rows = []
    for i, sym in enumerate(symbols):
        all_rows.extend(_contract_rows(sym, args.date, registry, seed=i))

    df = pd.DataFrame(all_rows)
    path = append_rows(df, args.date, args.out_root)
    print(f'Wrote {path} symbols={len(symbols)} contracts={len(df)}')


if __name__ == '__main__':
    main()
