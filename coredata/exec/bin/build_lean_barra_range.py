#!/usr/bin/env python3
"""
Batch-build Lean Barra exposures over a trading-day range.

Example::

    python3 build_lean_barra_range.py --start 20170522 --end 20260402 --history-days 1100
    python3 build_lean_barra_range.py --start 20180102 --end 20260402 --skip-existing --no-caffeinate
    python3 build_lean_barra_range.py --start 20170522 --end 20260402 --workers 4 --skip-existing --no-csv
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.lean_barra.paths import exposures_path
from lib.lean_barra.pipeline import build_daily_exposures, write_exposures
from lib.opcl.calendar import load_trading_days

PROGRESS_LOG = Path(__file__).resolve().parents[2] / 'data' / 'ref' / 'lean_barra_batch.log'


def _build_one_day(
    ymd: str,
    history_days: int,
    mad: float,
    fmp_api_key: str | None,
    write_csv: bool,
    skip_existing: bool,
) -> tuple[str, str, int, int, str | None]:
    """Worker: returns (ymd, status, rows, estu, error). status in ok|empty|skip|error."""
    if str(_BIN.parent) not in sys.path:
        sys.path.insert(0, str(_BIN.parent))
    from lib.lean_barra.paths import exposures_path as _exposures_path
    from lib.lean_barra.pipeline import build_daily_exposures as _build
    from lib.lean_barra.pipeline import write_exposures as _write

    if skip_existing and _exposures_path(ymd).exists():
        return ymd, 'skip', 0, 0, None
    try:
        exposures = _build(
            ymd,
            price_history_days=history_days,
            fmp_api_key=fmp_api_key,
            mad_multiplier=mad,
        )
        if exposures.empty:
            return ymd, 'empty', 0, 0, None
        _write(exposures, ymd, write_csv=write_csv)
        return ymd, 'ok', len(exposures), int(exposures['estu'].sum()), None
    except Exception as exc:
        return ymd, 'error', 0, 0, str(exc)


def parse_args():
    p = argparse.ArgumentParser(description='Batch Lean Barra exposure build')
    p.add_argument('--start', required=True, help='First trade date YYYYMMDD')
    p.add_argument('--end', required=True, help='Last trade date YYYYMMDD')
    p.add_argument('--history-days', type=int, default=1100,
                   help='Calendar days of equ history per date (RSTR needs ~504d)')
    p.add_argument('--mad', type=float, default=3.0)
    p.add_argument('--workers', type=int, default=1,
                   help='Parallel day builds (2-4 recommended on laptop SSD)')
    p.add_argument('--skip-existing', action='store_true', default=True)
    p.add_argument('--no-skip-existing', action='store_false', dest='skip_existing')
    p.add_argument('--no-csv', action='store_true', help='Parquet only (faster)')
    p.add_argument('--caffeinate', action='store_true', default=True)
    p.add_argument('--no-caffeinate', action='store_false', dest='caffeinate')
    p.add_argument('--fmp-api-key', default=None)
    p.add_argument('--limit', type=int, default=0, help='Max dates to build (0=all)')
    p.add_argument('--inner', action='store_true', help=argparse.SUPPRESS)
    return p.parse_args()


def _log(msg: str) -> None:
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
    print(line, flush=True)
    PROGRESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_LOG.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def _build_sequential(days: list[str], args: argparse.Namespace) -> tuple[int, int, int]:
    ok = skip = fail = 0
    for i, ymd in enumerate(days, 1):
        out = exposures_path(ymd)
        if args.skip_existing and out.exists():
            skip += 1
            continue
        try:
            exposures = build_daily_exposures(
                ymd,
                price_history_days=args.history_days,
                fmp_api_key=args.fmp_api_key,
                mad_multiplier=args.mad,
            )
            if exposures.empty:
                _log(f'[{i}/{len(days)}] {ymd} empty')
                fail += 1
                continue
            write_exposures(exposures, ymd, write_csv=not args.no_csv)
            ok += 1
            if i % 10 == 0 or i == len(days):
                _log(
                    f'[{i}/{len(days)}] {ymd} ok rows={len(exposures)} '
                    f'estu={int(exposures["estu"].sum())}'
                )
        except Exception as exc:
            _log(f'[{i}/{len(days)}] {ymd} error {exc}')
            fail += 1
    return ok, skip, fail


def _build_parallel(pending: list[tuple[int, str]], args: argparse.Namespace, n_days: int, skip: int) -> tuple[int, int, int]:
    ok = fail = 0
    extra_skip = 0
    done = 0
    write_csv = not args.no_csv
    _log(f'parallel workers={args.workers} pending={len(pending)}')
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _build_one_day,
                ymd,
                args.history_days,
                args.mad,
                args.fmp_api_key,
                write_csv,
                args.skip_existing,
            ): (idx, ymd)
            for idx, ymd in pending
        }
        for fut in as_completed(futures):
            idx, ymd = futures[fut]
            ymd_r, status, rows, estu, err = fut.result()
            done += 1
            pos = skip + done
            if status == 'ok':
                ok += 1
                if done % 10 == 0 or done == len(pending):
                    _log(f'[{pos}/{n_days}] {ymd_r} ok rows={rows} estu={estu}')
            elif status == 'skip':
                extra_skip += 1
            elif status == 'empty':
                fail += 1
                _log(f'[{pos}/{n_days}] {ymd_r} empty')
            else:
                fail += 1
                _log(f'[{pos}/{n_days}] {ymd_r} error {err}')
    return ok, skip + extra_skip, fail


def run_batch(args: argparse.Namespace) -> int:
    days = load_trading_days(args.start, args.end, feature_fallback=False)
    if not days:
        raise SystemExit(f'No trading days in {args.start}..{args.end}')
    if args.limit and args.limit > 0:
        days = days[: args.limit]

    skip = sum(1 for ymd in days if args.skip_existing and exposures_path(ymd).exists())
    pending = [
        (i, ymd) for i, ymd in enumerate(days, 1)
        if not (args.skip_existing and exposures_path(ymd).exists())
    ]

    _log(
        f'start batch n={len(days)} range={args.start}..{args.end} '
        f'history_days={args.history_days} workers={args.workers} '
        f'skip={skip} pending={len(pending)}'
    )

    if args.workers <= 1 or len(pending) <= 1:
        ok, skip, fail = _build_sequential(days, args)
    else:
        ok, skip, fail = _build_parallel(pending, args, len(days), skip)

    _log(f'done ok={ok} skip={skip} fail={fail}')
    return 0 if (ok > 0 or skip > 0) else 1


def main():
    if '--inner' not in sys.argv:
        argv = [a for a in sys.argv[1:] if a != '--caffeinate']
        if '--no-caffeinate' not in argv and shutil.which('caffeinate'):
            cmd = [sys.executable, str(Path(__file__).resolve()), '--inner', *argv]
            raise SystemExit(subprocess.call(['caffeinate', '-dimsu', *cmd]))
        sys.argv = [sys.argv[0], '--inner', *argv]

    args = parse_args()
    raise SystemExit(run_batch(args))


if __name__ == '__main__':
    main()
