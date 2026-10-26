#!/usr/bin/env python3
"""On-disk paths for Lean Barra factor exposures."""

from pathlib import Path

from ..paths import COREDATA_DIR, DEFAULT_REF_DIR, DEFAULT_UNIVERSE

PROD_ROOT = COREDATA_DIR / 'data' / 'prod' / 'na' / '3.0'
LEAN_BARRA = PROD_ROOT / 'lean_barra'
FUNDAMENTALS_CACHE = COREDATA_DIR / 'data' / 'ref' / 'fmp_fundamentals.parq'


def exposures_path(yyyymmdd: str) -> Path:
    return LEAN_BARRA / yyyymmdd[:4] / f'{yyyymmdd}.lean_barra_exposures.parq'


def exposures_csv_path(yyyymmdd: str) -> Path:
    return LEAN_BARRA / yyyymmdd[:4] / f'{yyyymmdd}.lean_barra_exposures.csv.gz'
