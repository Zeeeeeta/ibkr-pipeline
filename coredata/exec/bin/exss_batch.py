#!/usr/bin/env python3
"""Phase 2 batch: full-history EXSS features, annual refits, backtest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
PY = sys.executable


def parse_args():
    p = argparse.ArgumentParser(description='EXSS phase-2 batch runner')
    p.add_argument('--train-start', default='20170522',
                   help='First training date (9y window, aligned with Lean Barra)')
    p.add_argument('--train-end', default='20251231')
    p.add_argument('--predict-start', default='20180116',
                   help='First OOS predict day (~15d after first annual refit)')
    p.add_argument('--predict-end', default='20260402')
    p.add_argument('--skip-build', action='store_true')
    p.add_argument('--skip-refit', action='store_true')
    p.add_argument('--skip-predict', action='store_true')
    p.add_argument('--skip-backtest', action='store_true')
    p.add_argument('--xgb-python', default=None, help='Python with xgboost (default: same interpreter)')
    return p.parse_args()


def run(cmd: list[str]) -> None:
    print('>>', ' '.join(cmd))
    subprocess.check_call(cmd)


def main():
    args = parse_args()
    py = args.xgb_python or PY
    build = _BIN / 'build_exss_features.py'
    train = _BIN / 'exss_train_predict.py'
    bt = _BIN / 'exss_backtest.py'

    if not args.skip_build:
        run([py, str(build), '--start', args.train_start, '--end', args.predict_end])

    if not args.skip_refit:
        run([py, str(train), '--mode', 'refit-all',
             '--start', args.train_start, '--end', args.train_end])

    if not args.skip_predict:
        # predict each day in predict window
        from lib.exss.calendar import list_step2_dates
        sys.path.insert(0, str(_BIN.parent))
        for ymd in list_step2_dates(args.predict_start, args.predict_end):
            try:
                run([py, str(train), '--mode', 'predict', '--for-date', ymd,
                     '--start', args.train_start, '--end', args.predict_end])
            except subprocess.CalledProcessError as exc:
                print(f'skip predict {ymd}: {exc}')

    if not args.skip_backtest:
        run([py, str(bt), '--start', args.predict_start, '--end', args.predict_end])


if __name__ == '__main__':
    main()
