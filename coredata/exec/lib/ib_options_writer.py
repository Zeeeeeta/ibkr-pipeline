#!/usr/bin/env python3
"""Write IB options EOD rows to gzip CSV in CBOE v1.3 column layout."""

import os
from pathlib import Path

import pandas as pd

from .cboe_schema import CBOE_COLUMNS, FLOW_COLUMNS, OUTPUT_COLUMNS
from .paths import options_eod_path


def empty_row_template(flow_source: str = 'UNAVAILABLE_IB') -> dict:
    row = {c: None for c in OUTPUT_COLUMNS}
    row['flow_source'] = flow_source
    row['security_type'] = 1
    row['series_type'] = 'S'
    for col in FLOW_COLUMNS:
        row[col] = None
    return row


def append_rows(df: pd.DataFrame, yyyymmdd: str, out_root: Path) -> Path:
    """Append rows to the daily gzip file, creating header on first write."""
    if df.empty:
        raise ValueError('cannot append empty dataframe')

    path = options_eod_path(out_root, yyyymmdd)
    path.parent.mkdir(parents=True, exist_ok=True)

    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[OUTPUT_COLUMNS]

    write_header = not path.exists() or path.stat().st_size == 0
    df.to_csv(
        path,
        mode='a',
        index=False,
        header=write_header,
        compression='gzip',
    )
    return path


def read_day(yyyymmdd: str, out_root: Path) -> pd.DataFrame:
    path = options_eod_path(out_root, yyyymmdd)
    if not path.exists():
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.read_csv(path, compression='gzip')
