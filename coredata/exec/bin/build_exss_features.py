#!/usr/bin/env python3
"""Build EXSS step1 + step2 feature parquets."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.paths import step1_path, step2_path
from lib.exss.sid_map import build_sid_map_from_mk4
from lib.exss.step1 import write_step1
from lib.exss.step2 import build_step2
from lib.opcl.calendar import load_trading_days


def parse_args():
    p = argparse.ArgumentParser(description='Build EXSS step1/step2 parquets')
    p.add_argument('--for-date', default=None, help='Single YYYYMMDD')
    p.add_argument('--start', default=None)
    p.add_argument('--end', default=None)
    p.add_argument('--step', choices=('both', '1', '2'), default='both')
    p.add_argument('--skip-existing', action='store_true',
                   help='Skip dates that already have step1+step2 parquets')
    p.add_argument('--build-sid-map', action='store_true')
    return p.parse_args()


def _dates(args) -> list[str]:
    if args.for_date:
        return [args.for_date]
    if not args.start or not args.end:
        raise SystemExit('Provide --for-date or --start/--end')
    return load_trading_days(args.start, args.end, feature_fallback=False)


def main():
    args = parse_args()
    if args.build_sid_map:
        df = build_sid_map_from_mk4()
        print(f'Built sid map n={len(df)}')

    dates = _dates(args)
    if not dates:
        raise SystemExit('No trading dates')

    ok = skip = 0
    for ymd in dates:
        if args.skip_existing:
            if args.step == '1' and step1_path(ymd).exists():
                skip += 1
                continue
            if args.step == '2' and step2_path(ymd).exists():
                skip += 1
                continue
            if args.step == 'both' and step1_path(ymd).exists() and step2_path(ymd).exists():
                skip += 1
                continue
        try:
            if args.step in ('both', '1'):
                s1 = write_step1(ymd)
                if s1.empty:
                    print(f'{ymd} step1 empty (no short sale T-1)')
                    skip += 1
                    continue
            if args.step in ('both', '2'):
                s2 = build_step2(ymd)
                if s2.empty:
                    print(f'{ymd} step2 empty')
                    skip += 1
                    continue
                print(f'{ymd} step2 rows={len(s2)}')
            ok += 1
        except Exception as exc:
            print(f'{ymd} error: {exc}')
            skip += 1
    print(f'Done: ok={ok} skip={skip}')


if __name__ == '__main__':
    main()
