#!/usr/bin/env python3
"""
Build Lean Barra style factor exposures for a trade date.

Example::

    python3 build_lean_barra.py --for-date 20260402
    python3 build_lean_barra.py --for-date 20260402 --fmp-api-key $FMP_API_KEY
"""

import argparse
import json
import os
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.lean_barra.pipeline import build_daily_exposures, write_exposures


def parse_args():
    p = argparse.ArgumentParser(description='Build Lean Barra style factor exposures')
    p.add_argument('--for-date', help='YYYYMMDD trade date')
    p.add_argument('--universe', type=Path, default=None, help='Universe CSV (default: na_exch_screener)')
    p.add_argument('--fmp-api-key', default=os.environ.get('FMP_API_KEY'), help='FMP API key for value factor fundamentals')
    p.add_argument('--history-days', type=int, default=1100, help='Calendar days of price history to load')
    p.add_argument('--mad', type=float, default=3.0, help='MAD winsorization multiplier')
    p.add_argument('--no-csv', action='store_true', help='Skip gzip CSV sidecar')
    p.add_argument('--parity-check', action='store_true', help='Print prod parity checklist and exit')
    return p.parse_args()


def main():
    args = parse_args()
    if args.parity_check:
        from lib.lean_barra.residualize import parity_checklist
        print(json.dumps(parity_checklist(), indent=2))
        return
    if not args.for_date:
        print('error: --for-date is required unless --parity-check is set', file=sys.stderr)
        sys.exit(2)
    exposures = build_daily_exposures(
        args.for_date,
        universe_path=args.universe,
        price_history_days=args.history_days,
        fmp_api_key=args.fmp_api_key,
        mad_multiplier=args.mad,
    )
    if exposures.empty:
        print(f'No exposures built for {args.for_date} (check price files / universe)')
        sys.exit(1)

    out = write_exposures(exposures, args.for_date, write_csv=not args.no_csv)
    from lib.lean_barra.residualize import classify_factor_columns

    spec = classify_factor_columns(exposures)
    print(
        f'Wrote {out} rows={len(exposures)} estu={int(exposures["estu"].sum())} '
        f'styles={len(spec.style_cols)} industries={len(spec.industry_cols)}'
    )
    lb_preview = [c for c in exposures.columns if c.startswith('lb_')][:8]
    if lb_preview:
        print(exposures[lb_preview].describe().round(3).to_string())


if __name__ == '__main__':
    main()
