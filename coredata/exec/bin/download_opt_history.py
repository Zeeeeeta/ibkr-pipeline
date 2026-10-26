#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download universe option EOD files in CBOE Open/Close v1.3 layout (IB-sourced)."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.contract_builder import load_universe, process_symbol
from lib.ib_connect import connect_ib
from lib.ib_options_writer import append_rows
from lib.option_ids import SymbolSidRegistry
from lib.symbol_conid import SymbolConIdRegistry
from lib.paths import DEFAULT_OUT_ROOT, DEFAULT_UNIVERSE


def parse_args():
    p = argparse.ArgumentParser(description='IB options EOD downloader (CBOE v1.3 layout)')
    p.add_argument('--as-of', type=str, default=datetime.now().strftime('%Y%m%d'),
                 help='YYYYMMDD trade date anchor for expiry filter')
    p.add_argument('--test', type=int, default=None, help='Limit to first N symbols')
    p.add_argument('--universe', type=Path, default=DEFAULT_UNIVERSE)
    p.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument('--client-id', type=int, default=5)
    p.add_argument('--sleep-ms', type=int, default=30)
    p.add_argument('--max-expirations', type=int, default=3)
    p.add_argument('--strike-pct', type=float, default=0.15,
                 help='Strike band as fraction around ref price (0.15 = +/-15%%)')
    p.add_argument('--what-to-show', type=str, default='',
                 help='TRADES or MIDPOINT; empty = try TRADES then MIDPOINT')
    p.add_argument('--fetch-oi', action='store_true', help='Snapshot open interest (slower)')
    p.add_argument('--symbols', type=str, default='', help='Comma-separated symbols (overrides --test slice)')
    p.add_argument('--max-strikes', type=int, default=12, help='Max strikes per expiry near ATM')
    p.add_argument('--end-date', type=str, default='',
                 help='YYYYMMDD — anchor hist requests to this close (for equ alignment)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=7497)
    return p.parse_args()


def main():
    args = parse_args()
    if not args.universe.exists():
        raise FileNotFoundError(f'Universe not found: {args.universe}')

    filtered_df, symbols = load_universe(args.universe)
    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    elif args.test:
        symbols = symbols[: args.test]

    print(f'Universe: {len(symbols)} symbols | as-of {args.as_of} | out {args.out_root}')

    end_datetime = ''
    if args.end_date:
        end_datetime = f'{args.end_date[:4]}{args.end_date[4:6]}{args.end_date[6:8]} 16:00:00 US/Eastern'
        print(f'end-date anchor: {end_datetime}')

    registry = SymbolSidRegistry()
    conid_registry = SymbolConIdRegistry()
    ib = connect_ib(
        client_id=args.client_id,
        host=args.host,
        port=args.port,
        log_errors=True,
        request_timeout=45,
    )
    totals = {'symbols': 0, 'rows': 0, 'files': set()}

    try:
        for i, symbol in enumerate(symbols, 1):
            print(f'[{i}/{len(symbols)}] {symbol}')
            rows, stats = process_symbol(
                ib, symbol, filtered_df, registry, conid_registry,
                as_of_yyyymmdd=args.as_of,
                max_expirations=args.max_expirations,
                strike_pct=args.strike_pct,
                what_to_show=args.what_to_show,
                sleep_ms=args.sleep_ms,
                fetch_oi=args.fetch_oi,
                max_strikes=args.max_strikes,
                end_datetime=end_datetime,
                anchor_yyyymmdd=args.end_date or '',
            )
            if not rows:
                print(f'  skip: qualified={stats["qualified"]} qualify_fail={stats["skipped_qualify"]} hist_fail={stats["skipped_hist"]}')
                continue

            df = pd.DataFrame(rows)
            df['_ymd'] = pd.to_datetime(df['quote_date'], format='%m/%d/%Y').dt.strftime('%Y%m%d')
            for ymd, grp in df.groupby('_ymd'):
                path = append_rows(grp.drop(columns=['_ymd']), ymd, args.out_root)
                totals['files'].add(str(path))
                totals['rows'] += len(grp)
            totals['symbols'] += 1
            print(f'  ok: contracts={stats["qualified"]} day_rows={stats["rows"]}')
    except Exception as e:
        print(f'Fatal: {e}')
        raise
    finally:
        ib.disconnect()

    print(f'Done: symbols={totals["symbols"]} rows={totals["rows"]} files={len(totals["files"])}')


if __name__ == '__main__':
    main()
