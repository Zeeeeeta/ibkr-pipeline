#!/usr/bin/env python3
"""Repository path helpers."""

from pathlib import Path

EXEC_DIR = Path(__file__).resolve().parents[1]
COREDATA_DIR = EXEC_DIR.parent
REPO_ROOT = COREDATA_DIR.parent

DEFAULT_UNIVERSE = COREDATA_DIR / 'data' / 'univ' / '2026' / 'na_exch_screener_0418.csv'
DEFAULT_REF_DIR = COREDATA_DIR / 'data' / 'ref'
DEFAULT_OUT_ROOT = COREDATA_DIR / 'data' / 'prod' / 'na' / '3.0' / 'options_open_close'
PROBE_RESULTS = EXEC_DIR / 'schemas' / 'ib_probe_results.json'


def options_eod_path(out_root: Path, yyyymmdd: str) -> Path:
    y, m, d = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:8]
    return out_root / y / m / d / f'{yyyymmdd}.ib_options_eod.csv.gz'
