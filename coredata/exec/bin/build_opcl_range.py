#!/usr/bin/env python3
"""
Batch-build OPCL features over a trading-day range.

Steps per for_date T:
  1. Ensure options EOD exists for T-1 (seed if missing)
  2. Run build_sod_features --reduced

Requires equ_prices for T (and forward days for labels).
"""

import argparse
import subprocess
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.opcl.calendar import load_trading_days, opcl_trading_days
from lib.opcl.mk3_io import load_options_day


DEFAULT_SYMBOLS = (
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM',
    'V', 'UNH', 'XOM', 'LLY', 'AVGO', 'MA', 'COST',
)


def parse_args():
    p = argparse.ArgumentParser(description='Batch seed options + build OPCL features')
    p.add_argument('--start', required=True, help='First for_date YYYYMMDD')
    p.add_argument('--end', required=True, help='Last for_date YYYYMMDD')
    p.add_argument('--symbols', default=','.join(DEFAULT_SYMBOLS))
    p.add_argument('--seed-missing-options', action='store_true', default=True)
    p.add_argument('--no-seed', dest='seed_missing_options', action='store_false')
    p.add_argument('--reduced', action='store_true', default=True)
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def equ_exists(ymd: str) -> bool:
    from lib.opcl.paths import equ_prices_path
    return equ_prices_path(ymd).exists()


def prior_trading_day(for_date: str, trading_days: list[str]) -> str | None:
    prior = [d for d in trading_days if d < for_date]
    return prior[-1] if prior else None


def seed_options(quote_date: str, symbols: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(_BIN / 'seed_ib_options_eod.py'),
            '--date', quote_date,
            '--symbols', symbols,
            '--append-missing',
        ],
        check=True,
    )


def build_features(for_date: str, reduced: bool) -> None:
    cmd = [sys.executable, str(_BIN / 'build_sod_features.py'), '--for-date', for_date]
    if reduced:
        cmd.append('--reduced')
    subprocess.run(cmd, check=True)


def main():
    args = parse_args()
    trading_days = [
        d for d in opcl_trading_days(args.start, args.end)
        if args.start <= d <= args.end and equ_exists(d)
    ]
    if not trading_days:
        raise SystemExit(f'No trading days with equ_prices in {args.start}..{args.end}')

    cal_days = load_trading_days(args.start, args.end, feature_fallback=False)
    built = skipped = seeded = 0

    print(f'for_dates with equ: {len(trading_days)} ({trading_days[0]}..{trading_days[-1]})')

    for for_date in trading_days:
        t1 = prior_trading_day(for_date, cal_days or trading_days)
        if t1 is None:
            print(f'skip {for_date}: no prior trading day')
            skipped += 1
            continue

        if load_options_day(t1).empty:
            if not args.seed_missing_options:
                print(f'skip {for_date}: no options on T-1={t1}')
                skipped += 1
                continue
            print(f'seed options {t1} for for_date={for_date}')
            if args.dry_run:
                seeded += 1
                continue
            seed_options(t1, args.symbols)
            seeded += 1

        if args.dry_run:
            print(f'would build features {for_date}')
            built += 1
            continue

        try:
            build_features(for_date, args.reduced)
            built += 1
        except subprocess.CalledProcessError as exc:
            print(f'FAIL {for_date}: {exc}')
            skipped += 1

    print(f'Done: built={built} seeded={seeded} skipped={skipped}')


if __name__ == '__main__':
    main()
