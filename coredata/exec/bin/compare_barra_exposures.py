#!/usr/bin/env python3
"""Compare Lean Barra exposures against official mk4 for calibration."""

import argparse
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.lean_barra.mk4_loader import compare_to_lean, load_mk4, normalize_mk4
from lib.lean_barra.pipeline import load_exposures
from lib.opcl.paths import BARRA


def parse_args():
    p = argparse.ArgumentParser(description='Compare Lean vs official Barra exposures')
    p.add_argument('--for-date', required=True, help='YYYYMMDD')
    p.add_argument('--tickers', default='PLD,AMN,AKR,ACM,AAPL', help='Comma-separated tickers')
    p.add_argument('--mk4', type=Path, default=None, help='Path to mk4 file (default: prod barra dir)')
    return p.parse_args()


def main():
    args = parse_args()
    tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]

    mk4_path = args.mk4 or (BARRA / args.for_date[:4] / f'{args.for_date}.usfastd_rsk.rev.mk4.csv.gz')
    lean = load_exposures(args.for_date)

    if args.mk4 and args.mk4.suffix != '.gz':
        # Allow pasting a pipe-delimited snippet saved as .csv
        official = normalize_mk4(__import__('pandas').read_csv(args.mk4, sep='|', skipinitialspace=True))
    elif mk4_path.exists():
        official = load_mk4(mk4_path)
    else:
        print(f'No mk4 file at {mk4_path}')
        print('Place official file there or pass --mk4 /path/to/file')
        sys.exit(1)

    if lean.empty:
        print(f'No lean exposures for {args.for_date}; run build_lean_barra.py first')
        sys.exit(1)

    cmp = compare_to_lean(official, lean, tickers)
    if cmp.empty:
        print('No overlapping tickers found')
        sys.exit(1)

    pd = __import__('pandas')
    print(cmp.pivot(index='symbol', columns='factor', values='delta').round(3).to_string())
    print()
    print(cmp.groupby('factor')[['barra', 'lean', 'delta']].mean().round(3).to_string())


if __name__ == '__main__':
    main()
