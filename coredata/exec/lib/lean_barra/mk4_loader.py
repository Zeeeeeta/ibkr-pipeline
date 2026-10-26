#!/usr/bin/env python3
"""Load and normalize official ``usfastd_rsk.rev.mk4`` Barra risk model files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .risk_model import INTERCEPT_FACTOR, OFFICIAL_STYLE_FACTORS

INDNAME_COLS = [f'indname{i}' for i in range(1, 6)]
WGT_COLS = [f'wgt{i}' for i in range(1, 6)]


def _norm_industry_col(name: str) -> str:
    """``USFASTD_REALEST`` -> ``usfastd_realest``."""
    s = str(name or '').strip().lower()
    if not s or s in ('nan', 'none'):
        return ''
    if not s.startswith('usfastd_'):
        s = f'usfastd_{s}'
    return s


def expand_industry_exposures(df: pd.DataFrame) -> pd.DataFrame:
    """
    Expand ``indname1..5`` + ``wgt1..5`` into industry exposure columns.

    Prod stores sparse industry assignments; residualization needs a dense matrix.
    Weights sum to 1.0 per stock (e.g. AMN: 0.645 HLTHSVCS + 0.355 COMSVCS).
    """
    if not any(c in df.columns for c in INDNAME_COLS):
        return df

    out = df.copy()
    industries: set[str] = set()
    row_maps: list[dict[str, float]] = []

    for _, row in out.iterrows():
        exp: dict[str, float] = {}
        for iname, iwgt in zip(INDNAME_COLS, WGT_COLS):
            if iname not in row.index or iwgt not in row.index:
                continue
            col = _norm_industry_col(row[iname])
            w = float(row[iwgt]) if pd.notna(row[iwgt]) and str(row[iwgt]).strip() else 0.0
            if col and w != 0.0:
                exp[col] = exp.get(col, 0.0) + w
                industries.add(col)
        row_maps.append(exp)

    for ind in sorted(industries):
        out[ind] = [m.get(ind, 0.0) for m in row_maps]

    return out


def normalize_mk4(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase style columns, map ticker->symbol, expand industries."""
    out = df.copy()
    out.columns = [c.strip().lower() for c in out.columns]

    renames = {}
    if 'ticker' in out.columns and 'symbol' not in out.columns:
        renames['ticker'] = 'symbol'
    if 'sid' in out.columns and 'tid' not in out.columns:
        renames['sid'] = 'tid'
    out = out.rename(columns=renames)

    # Fix common typos / aliases in upstream extracts.
    if 'uastd_momentum' in out.columns and 'usfastd_momentum' not in out.columns:
        out['usfastd_momentum'] = out['uastd_momentum']

    for col in OFFICIAL_STYLE_FACTORS:
        if col not in out.columns:
            # Try case-insensitive match from source file.
            for c in df.columns:
                if c.strip().lower() == col:
                    out[col] = df[c]
                    break

    if INTERCEPT_FACTOR not in out.columns:
        out[INTERCEPT_FACTOR] = 1.0

    out = expand_industry_exposures(out)
    return out


def _read_mk4_csv(path: Path) -> pd.DataFrame:
    """Auto-detect pipe vs comma delimiter (prod files use comma)."""
    with open(path, 'rb') as f:
        if str(path).endswith('.gz'):
            import gzip
            head = gzip.open(path, 'rt').readline()
        else:
            head = f.readline().decode()
    sep = '|' if head.count('|') > head.count(',') else ','
    return pd.read_csv(path, compression='gzip' if str(path).endswith('.gz') else None, sep=sep)


def load_mk4(path: Path | str) -> pd.DataFrame:
    return normalize_mk4(_read_mk4_csv(Path(path)))


def compare_to_lean(
    official: pd.DataFrame,
    lean: pd.DataFrame,
    tickers: list[str],
) -> pd.DataFrame:
    """Side-by-side style exposures for calibration."""
    from .risk_model import LEAN_TO_OFFICIAL_STYLE

    rows = []
    off = official.set_index('symbol') if 'symbol' in official.columns else official
    le = lean.set_index('symbol') if 'symbol' in lean.columns else lean

    for t in tickers:
        if t not in off.index or t not in le.index:
            continue
        for lb_col, us_col in LEAN_TO_OFFICIAL_STYLE.items():
            if us_col not in off.columns:
                continue
            barra_val = off.loc[t, us_col]
            lean_val = le.loc[t, lb_col] if lb_col in le.columns else np.nan
            rows.append({
                'symbol': t,
                'factor': us_col.replace('usfastd_', ''),
                'barra': float(barra_val),
                'lean': float(lean_val) if pd.notna(lean_val) else np.nan,
                'delta': float(lean_val - barra_val) if pd.notna(lean_val) else np.nan,
            })
    return pd.DataFrame(rows)
