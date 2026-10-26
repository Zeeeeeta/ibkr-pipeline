#!/usr/bin/env python3
"""EXSS ablation grid: 16 combos × refit-all × backtest."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.exss.calendar import list_step2_dates, training_dates_before, year_end_trading_dates
from lib.exss.config_exp import (
    EXPERIMENTS_SUMMARY_CSV,
    experiment_models_dir,
    experiment_slug,
    get_experiment_combinations,
    set_experiment_config,
)
from lib.exss.paths import EXSS_OUT, step2_path

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PY = Path(
    os.environ.get(
        'EXSS_XGB_PYTHON',
        str(_REPO_ROOT / '.mamba/envs/.venv-opcl/bin/python'),
    )
)
if not Path(DEFAULT_PY).exists():
    DEFAULT_PY = Path(sys.executable)


def parse_args():
    p = argparse.ArgumentParser(description='EXSS ablation grid runner')
    p.add_argument('--train-start', default='20170522')
    p.add_argument('--train-end', default='20251231')
    p.add_argument('--predict-start', default='20180116')
    p.add_argument('--predict-end', default='20260402')
    p.add_argument('--python', default=str(DEFAULT_PY))
    p.add_argument('--skip-existing', action='store_true',
                   help='Skip combos that already have status=ok in summary')
    p.add_argument('--retry-failed', action='store_true',
                   help='Run only combos whose last summary status is error')
    p.add_argument('--only', default=None, help='Run single experiment slug')
    p.add_argument('--smoke', action='store_true',
                   help='Quick smoke: refit 20231229 + 2024 backtest')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def _sharpe(rets: list[float]) -> float:
    arr = np.array([x for x in rets if np.isfinite(x)])
    if len(arr) < 2:
        return 0.0
    sd = arr.std(ddof=1)
    return float(arr.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0


def _run_cmd(cmd: list[str], env: dict) -> None:
    print('>>', ' '.join(cmd), flush=True)
    subprocess.check_call(cmd, env=env)


def _smoke_refit(train_start: str, refit_dates: list[str], cfg: dict) -> None:
    set_experiment_config(cfg)
    from lib.exss.train_predict import fit_model, save_model
    from lib.exss.paths import active_models_dir

    print(f'Smoke models dir: {active_models_dir()}', flush=True)
    for refit_date in refit_dates:
        available = list_step2_dates(train_start, refit_date)
        train_dates = training_dates_before(refit_date, available)
        frames = [pd.read_parquet(step2_path(d)) for d in train_dates if step2_path(d).exists()]
        train = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if train.empty:
            raise RuntimeError(f'No training data before {refit_date}')
        model, feature_cols = fit_model(train)
        save_model(
            model, refit_date,
            n_train_days=len(train_dates),
            n_train_rows=len(train),
            feature_cols=feature_cols,
        )
        print(f'Smoke refit {refit_date}: features={feature_cols}')


def _run_one_combo(
    cfg: dict,
    *,
    py: str,
    train_start: str,
    train_end: str,
    predict_start: str,
    predict_end: str,
    smoke: bool,
    dry_run: bool,
) -> dict:
    slug = experiment_slug(cfg)
    env = os.environ.copy()
    env['EXSS_EXP_CONFIG'] = json.dumps(cfg, sort_keys=True)

    train = _BIN / 'exss_train_predict.py'
    bt = _BIN / 'exss_backtest.py'

    if smoke:
        predict_start = '20240116'
        predict_end = '20241231'
        train_end = '20241231'

    bt_out = EXSS_OUT / f'backtest_{predict_start}_{predict_end}_{slug}.csv'

    if dry_run:
        return {'experiment': slug, **cfg, 'status': 'dry_run'}

    if smoke:
        _smoke_refit(train_start, ['20231229'], cfg)
    else:
        _run_cmd([
            py, str(train), '--mode', 'refit-all',
            '--start', train_start, '--end', train_end,
        ], env)

    return_col = cfg['label_window']
    _run_cmd([
        py, str(bt),
        '--start', predict_start,
        '--end', predict_end,
        '--return-col', return_col,
        '--output', str(bt_out),
    ], env)

    bt_df = pd.read_csv(bt_out)
    rets = bt_df['port_ret'].dropna().tolist()
    return {
        'experiment': slug,
        **cfg,
        'status': 'ok',
        'period_start': bt_df['quote_ymd'].iloc[0],
        'period_end': bt_df['quote_ymd'].iloc[-1],
        'days': int(len(bt_df)),
        'hit_rate': float((bt_df['port_ret'] > 0).mean()),
        'mean_daily': float(np.nanmean(rets)),
        'sharpe_252': _sharpe(rets),
        'total_pnl': float(bt_df['port_ret'].fillna(0).sum()),
        'backtest_csv': str(bt_out),
        'models_dir': str(experiment_models_dir(cfg)),
        'run_ts': datetime.now(timezone.utc).isoformat(),
    }


def _append_summary(row: dict) -> None:
    EXPERIMENTS_SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if EXPERIMENTS_SUMMARY_CSV.exists():
        old = pd.read_csv(EXPERIMENTS_SUMMARY_CSV)
        old = old[old['experiment'] != row['experiment']]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(EXPERIMENTS_SUMMARY_CSV, index=False)
    print(f'Appended {row["experiment"]} -> {EXPERIMENTS_SUMMARY_CSV}')


def main():
    args = parse_args()
    combos = get_experiment_combinations()
    if args.retry_failed and EXPERIMENTS_SUMMARY_CSV.exists():
        prev = pd.read_csv(EXPERIMENTS_SUMMARY_CSV)
        failed = prev.loc[prev['status'].astype(str).str.startswith('error'), 'experiment']
        combos = [c for c in combos if experiment_slug(c) in set(failed)]
        print(f'Retry-failed: {len(combos)} combo(s)')
    if args.only:
        combos = [c for c in combos if experiment_slug(c) == args.only]
        if not combos:
            raise SystemExit(f'Unknown slug: {args.only}')

    print(f'Running {len(combos)} experiment(s)')
    for i, cfg in enumerate(combos, 1):
        slug = experiment_slug(cfg)
        print(f'\n=== [{i}/{len(combos)}] {slug} ===')
        set_experiment_config(cfg)

        if args.skip_existing and EXPERIMENTS_SUMMARY_CSV.exists():
            prev = pd.read_csv(EXPERIMENTS_SUMMARY_CSV)
            ok = prev.loc[prev['status'].astype(str).eq('ok'), 'experiment']
            if slug in set(ok):
                print(f'skip existing {slug}')
                continue

        try:
            row = _run_one_combo(
                cfg,
                py=args.python,
                train_start=args.train_start,
                train_end=args.train_end,
                predict_start=args.predict_start,
                predict_end=args.predict_end,
                smoke=args.smoke,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                _append_summary(row)
                print(
                    f"  sharpe={row['sharpe_252']:.3f} "
                    f"hit={row['hit_rate']:.3f} "
                    f"mean={row['mean_daily']:.6f}"
                )
        except (subprocess.CalledProcessError, RuntimeError, KeyError) as exc:
            err_row = {'experiment': slug, **cfg, 'status': f'error:{exc}'}
            _append_summary(err_row)
            print(f'FAILED {slug}: {exc}')


if __name__ == '__main__':
    main()
