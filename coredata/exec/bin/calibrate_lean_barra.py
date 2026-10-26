#!/usr/bin/env python3
"""
Calibration report: Lean Barra vs official mk4 (sample week only).

Official files are benchmarks, not production inputs. Use this to track
parity before relying on Lean for daily residualization / optimization.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.lean_barra.mk4_loader import load_mk4
from lib.lean_barra.pipeline import build_daily_exposures, load_exposures, write_exposures
from lib.lean_barra.risk_model import LEAN_TO_OFFICIAL_STYLE, OFFICIAL_STYLE_FACTORS
from lib.opcl.paths import BARRA


def parse_args():
    p = argparse.ArgumentParser(description='Lean vs Barra calibration report')
    p.add_argument('--for-date', help='Single YYYYMMDD (default: all mk4 in barra dir)')
    p.add_argument('--rebuild', action='store_true', help='Rebuild Lean exposures before compare')
    p.add_argument('--tickers', default='', help='Optional comma-separated tickers for detail table')
    return p.parse_args()


def _dates(args) -> list[str]:
    if args.for_date:
        return [args.for_date]
    year_dir = BARRA / '2026'
    if not year_dir.exists():
        return []
    return sorted(p.stem.split('.')[0] for p in year_dir.glob('*.mk4.csv.gz'))


def _lean_for_date(d: str, rebuild: bool) -> pd.DataFrame:
    if rebuild:
        exp = build_daily_exposures(d)
        if not exp.empty:
            write_exposures(exp, d, write_csv=False)
        return exp
    lean = load_exposures(d)
    return lean if not lean.empty else build_daily_exposures(d)


def main():
    args = parse_args()
    tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]
    rows: list[dict] = []

    for d in _dates(args):
        mk4_path = BARRA / d[:4] / f'{d}.usfastd_rsk.rev.mk4.csv.gz'
        if not mk4_path.exists():
            print(f'skip {d}: no mk4 at {mk4_path}')
            continue
        official = load_mk4(mk4_path)
        lean = _lean_for_date(d, args.rebuild)
        if lean.empty:
            print(f'skip {d}: lean build empty')
            continue

        estu = official[official['estu'] == 1]
        merged = lean.merge(
            estu[['symbol'] + list(OFFICIAL_STYLE_FACTORS)],
            on='symbol',
            how='inner',
            suffixes=('_lean', '_barra'),
        )
        if merged.empty:
            print(f'skip {d}: no symbol overlap with Barra ESTU')
            continue

        for us in OFFICIAL_STYLE_FACTORS:
            lb = next((k for k, v in LEAN_TO_OFFICIAL_STYLE.items() if v == us), None)
            barra_col = us if us in merged.columns else f'{us}_barra'
            if not lb or lb not in merged.columns or barra_col not in merged.columns:
                continue
            b = merged[barra_col].astype(float)
            l = merged[lb].astype(float)
            rows.append({
                'date': d,
                'factor': us.replace('usfastd_', ''),
                'n': len(merged),
                'corr': l.corr(b),
                'rmse': ((l - b) ** 2).mean() ** 0.5,
                'mad': (l - b).abs().mean(),
            })

        if tickers:
            from lib.lean_barra.mk4_loader import compare_to_lean

            cmp = compare_to_lean(official, lean, tickers)
            print(f'\n=== {d} ticker deltas ===')
            print(cmp.pivot(index='symbol', columns='factor', values='delta').round(3).to_string())

    if not rows:
        sys.exit(1)

    rep = pd.DataFrame(rows)
    summary = rep.groupby('factor')[['corr', 'rmse', 'mad']].mean().round(3).sort_values('mad', ascending=False)
    print('\n=== Calibration summary (mean over dates, ESTU overlap) ===')
    print(summary.to_string())
    print(f'\nDates: {sorted(rep["date"].unique())}  overlap n≈{int(rep["n"].median())}')


if __name__ == '__main__':
    main()
