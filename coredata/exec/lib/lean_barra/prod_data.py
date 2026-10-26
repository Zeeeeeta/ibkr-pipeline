#!/usr/bin/env python3
"""Load prod ``YYYYMMDD.data.parquet`` return panels for validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from lib.paths import COREDATA_DIR

DEFAULT_PROD_DATA_DIR = Path.home() / "Downloads"
PROD_DATA_DIR = COREDATA_DIR / 'data' / 'ref' / 'prod_returns'


def prod_data_path(for_date: str, root: Path | None = None) -> Path:
    root = root or DEFAULT_PROD_DATA_DIR
    return root / f'{for_date}.data.parquet'


def load_prod_returns(
    for_date: str,
    *,
    root: Path | None = None,
    tod_hour: int = 16,
    tid_map: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Load prod intraday return panel at ``tod_hour`` (default 16:00 = market close).

    Returns one row per ``tid`` with raw and residual return columns.
    """
    p = prod_data_path(for_date, root)
    df = pd.read_parquet(p).reset_index()
    df['hour'] = pd.to_datetime(df['time']).dt.hour
    sub = df[df['hour'] == tod_hour].copy()
    if tid_map is not None and 'tid' in sub.columns:
        sub = sub.merge(tid_map, on='tid', how='left')
    return sub


def tid_ticker_map_from_mk4(for_date: str, barra_root: Path | None = None) -> pd.DataFrame:
    from ..opcl.paths import BARRA
    from .mk4_loader import load_mk4

    root = barra_root or BARRA
    p = root / for_date[:4] / f'{for_date}.usfastd_rsk.rev.mk4.csv.gz'
    mk4 = load_mk4(p)
    cols = ['tid', 'symbol'] if 'tid' in mk4.columns else ['sid', 'symbol']
    if 'tid' not in mk4.columns:
        mk4 = mk4.rename(columns={'sid': 'tid'})
    return mk4[['tid', 'symbol']].drop_duplicates()
