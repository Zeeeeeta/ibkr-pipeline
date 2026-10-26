#!/usr/bin/env python3
"""Fetch daily stock bars from IB and write equ_prices CSV files."""

import argparse
import sys
import time
from datetime import datetime, timezone

import pandas as pd
from ib_async import Stock, util

from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.ib_connect import DEFAULT_HOST, DEFAULT_PORT, connect_ib
from lib.opcl.calendar import load_trading_days
from lib.opcl.equ_fetch import (
    EQU_OUTPUT_COLS,
    load_backfill_progress,
    load_universe_symbols,
    resolve_history_start,
    save_backfill_progress,
    symbol_backfill_complete,
    write_symbol_panel,
)
from lib.paths import DEFAULT_UNIVERSE

DEFAULT_SYMBOLS = (
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM',
    'V', 'UNH', 'XOM', 'LLY', 'AVGO', 'MA', 'COST',
)


def parse_args():
    p = argparse.ArgumentParser(description='Fetch IB equity daily bars into equ_prices')
    p.add_argument('--universe', type=Path, default=DEFAULT_UNIVERSE,
                   help='Universe CSV (default: na_exch_screener); used when --symbols omitted')
    p.add_argument('--symbols', default=None,
                   help='Comma-separated tickers (overrides --universe)')
    p.add_argument('--start', default=None, help='YYYYMMDD inclusive')
    p.add_argument('--end', required=True, help='YYYYMMDD inclusive')
    p.add_argument('--train-years', type=float, default=None,
                   help='Set start to ~N trading years before --end (alternative to --start)')
    p.add_argument('--chunk-years', type=int, default=1,
                   help='IB hist request chunk size in years (default 1)')
    p.add_argument('--client-id', type=int, default=70)
    p.add_argument('--sleep-ms', type=int, default=350,
                   help='Pause between IB requests')
    p.add_argument('--skip-existing', action='store_true',
                   help='Skip symbols already backfilled for this start/end window')
    p.add_argument('--offset', type=int, default=0, help='Skip first N symbols (batching)')
    p.add_argument('--limit', type=int, default=0, help='Max symbols to fetch (0 = all)')
    p.add_argument('--reconnect-every', type=int, default=250,
                   help='Reconnect IB session every N symbols (0 = never)')
    p.add_argument('--ib-host', default=None, help='IB Gateway/TWS host (default: IB_HOST env or 127.0.0.1)')
    p.add_argument('--ib-port', type=int, default=None, help='Socket port (Gateway paper 4002, TWS paper 7497)')
    return p.parse_args()


def qualify_stock(ib, symbol: str):
    stk = Stock(symbol, 'SMART', 'USD')
    q = ib.qualifyContracts(stk)
    if q:
        return q[0]
    details = ib.reqContractDetails(stk)
    if not details:
        return None
    return details[0].contract


def fetch_chunk(ib, contract, end_yyyymmdd: str, years: int) -> pd.DataFrame:
    end = f'{end_yyyymmdd} 16:00:00 US/Eastern'
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end,
        durationStr=f'{years} Y',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        return pd.DataFrame()
    df = util.df(bars)
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
    return df


def _chunk_end_for_year(year: int, end: str, trading_days: list[str]) -> str:
    year_days = [d for d in trading_days if d.startswith(str(year))]
    if year_days:
        cap = min(end, year_days[-1])
        prior = [d for d in year_days if d <= cap]
        if prior:
            return prior[-1]
    return min(end, f'{year}1231')


def fetch_symbol_history(
    ib,
    symbol: str,
    start: str,
    end: str,
    *,
    chunk_years: int = 1,
    sleep_ms: int = 350,
    trading_days: list[str] | None = None,
) -> pd.DataFrame:
    contract = qualify_stock(ib, symbol)
    if contract is None:
        return pd.DataFrame()

    td = trading_days or []
    frames = []
    end_year = int(end[:4])
    start_year = int(start[:4])
    for year in range(end_year, start_year - 1, -chunk_years):
        chunk_end = _chunk_end_for_year(year, end, td)
        df = fetch_chunk(ib, contract, chunk_end, chunk_years)
        time.sleep(sleep_ms / 1000.0)
        if df.empty:
            continue
        df['symbol'] = symbol
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(['symbol', 'date'])
    out = out[(out['date'] >= start) & (out['date'] <= end)]
    for c in EQU_OUTPUT_COLS:
        if c not in out.columns:
            if c == 'average' and 'wap' in out.columns:
                out['average'] = out['wap']
            else:
                out[c] = pd.NA
    return out[EQU_OUTPUT_COLS]


def _resolve_symbols(args) -> list[str]:
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    if args.universe and Path(args.universe).exists():
        return load_universe_symbols(args.universe)
    return list(DEFAULT_SYMBOLS)


def main():
    args = parse_args()
    start = resolve_history_start(args.end, args.train_years, args.start)
    symbols = _resolve_symbols(args)
    if args.offset:
        symbols = symbols[args.offset:]
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]

    td_list = load_trading_days(start, args.end, feature_fallback=False)
    trading_days = set(td_list)
    expected_days = len(td_list)
    progress = load_backfill_progress()

    ib_host = args.ib_host or DEFAULT_HOST
    ib_port = args.ib_port or DEFAULT_PORT

    print(f'Fetching {len(symbols)} symbols  {start}..{args.end}  chunk={args.chunk_years}Y')
    print(f'  IB {ib_host}:{ib_port} clientId={args.client_id}')
    if args.train_years:
        print(f'  train-years={args.train_years} -> start={start}  expected_days={expected_days}')

    ib = connect_ib(client_id=args.client_id, host=ib_host, port=ib_port, log_errors=True, request_timeout=120)
    ib.reqMarketDataType(3)
    ok = skip = fail = 0
    try:
        for i, sym in enumerate(symbols, 1):
            if args.skip_existing and symbol_backfill_complete(
                sym, start, args.end, expected_days=expected_days, progress=progress,
            ):
                print(f'[{i}/{len(symbols)}] {sym} skip (already backfilled)')
                skip += 1
                continue

            if args.reconnect_every and i > 1 and (i - 1) % args.reconnect_every == 0:
                ib.disconnect()
                time.sleep(2)
                ib = connect_ib(client_id=args.client_id, host=ib_host, port=ib_port, log_errors=True, request_timeout=120)
                ib.reqMarketDataType(3)

            print(f'[{i}/{len(symbols)}] {sym} ...', end=' ', flush=True)
            try:
                df = fetch_symbol_history(
                    ib, sym, start, args.end,
                    chunk_years=args.chunk_years,
                    sleep_ms=args.sleep_ms,
                    trading_days=td_list,
                )
            except Exception as exc:
                print(f'error {exc}')
                fail += 1
                save_backfill_progress({
                    'symbol': sym,
                    'start': start,
                    'end': args.end,
                    'n_days': 0,
                    'status': 'error',
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                })
                continue

            if df.empty:
                print('no bars')
                fail += 1
                save_backfill_progress({
                    'symbol': sym,
                    'start': start,
                    'end': args.end,
                    'n_days': 0,
                    'status': 'empty',
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                })
                continue

            if trading_days:
                df = df[df['date'].isin(trading_days)]
            n_days = write_symbol_panel(df)
            print(f'{n_days} days written')
            ok += 1
            save_backfill_progress({
                'symbol': sym,
                'start': start,
                'end': args.end,
                'n_days': n_days,
                'status': 'ok',
                'updated_at': datetime.now(timezone.utc).isoformat(),
            })
    finally:
        ib.disconnect()

    print(f'Done: ok={ok} skip={skip} fail={fail}  window={start}..{args.end}')
    if ok == 0 and skip == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
