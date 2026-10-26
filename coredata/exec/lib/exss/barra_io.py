#!/usr/bin/env python3
"""Barra style load with Lean Barra first, mk4 fallback."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..lean_barra.mk4_loader import load_mk4
from ..lean_barra.pipeline import load_exposures
from ..lean_barra.risk_model import OFFICIAL_STYLE_FACTORS
from ..opcl.paths import BARRA


def mk4_path(yyyymmdd: str) -> Path:
    return BARRA / yyyymmdd[:4] / f'{yyyymmdd}.usfastd_rsk.rev.mk4.csv.gz'


def load_barra_day(for_date: str, *, max_lag: int = 4) -> pd.DataFrame:
    """Prefer daily Lean Barra exposures; fall back to official mk4 with lag."""
    dt = datetime.strptime(for_date, '%Y%m%d')
    for lag in range(max_lag + 1):
        ymd = (dt - timedelta(days=lag)).strftime('%Y%m%d')
        lean = load_exposures(ymd)
        if not lean.empty and 'symbol' in lean.columns:
            return lean
    for lag in range(max_lag + 1):
        ymd = (dt - timedelta(days=lag)).strftime('%Y%m%d')
        p = mk4_path(ymd)
        if p.exists():
            return load_mk4(p)
    return pd.DataFrame()


STYLE_COLS = list(OFFICIAL_STYLE_FACTORS) + ['usfastd_country']


def barra_styles(for_date: str) -> pd.DataFrame:
    df = load_barra_day(for_date)
    if df.empty or 'symbol' not in df.columns:
        return pd.DataFrame(columns=['symbol'] + STYLE_COLS)
    cols = ['symbol'] + [c for c in STYLE_COLS if c in df.columns]
    out = df[cols].copy()
    out['symbol'] = out['symbol'].astype(str).str.upper()
    return out.drop_duplicates('symbol')
