#!/usr/bin/env python3
"""Load mk3 / IB EOD option files and merge supplements."""

from pathlib import Path

import pandas as pd

from ..cboe_schema import FLOW_COLUMNS
from .paths import ib_options_eod, mk3_path, noto_path, photo_path


def _read_gz(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, compression='gzip' if str(path).endswith('.gz') else None)


def load_options_day(yyyymmdd: str) -> pd.DataFrame:
    """Prefer prod mk3; else IB EOD file."""
    for p in (mk3_path(yyyymmdd), ib_options_eod(yyyymmdd)):
        if p.exists():
            df = _read_gz(p)
            if not df.empty:
                df['_source_file'] = p.name
                return df
    return pd.DataFrame()


def has_flow_data(df: pd.DataFrame) -> bool:
    """True when participant flow cols carry real (non-zero) quantities."""
    if df.empty:
        return False
    if 'flow_source' in df.columns:
        sources = df['flow_source'].dropna().unique()
        if len(sources) and all(str(s) == 'UNAVAILABLE_IB' for s in sources):
            return False
    qty_cols = [c for c in FLOW_COLUMNS if c.endswith('_qty') and c in df.columns]
    if not qty_cols:
        return False
    vals = df[qty_cols].fillna(0)
    return bool((vals != 0).any().any())


def merge_supplements(df: pd.DataFrame, yyyymmdd: str) -> pd.DataFrame:
    """Add noto/photo flow columns when files exist (numeric add on overlapping cols)."""
    if df.empty:
        return df
    out = df.copy()
    for loader in (noto_path, photo_path):
        p = loader(yyyymmdd)
        sup = _read_gz(p)
        if sup.empty:
            continue
        flow = [c for c in FLOW_COLUMNS if c in sup.columns and c in out.columns]
        if not flow:
            continue
        keys = [k for k in ('sid', 'optsid', 'underlying_symbol', 'strike_price', 'call_put_flag')
                if k in out.columns and k in sup.columns]
        if not keys:
            continue
        merged = out.merge(sup[keys + flow], on=keys, how='outer', suffixes=('', '_sup'))
        for c in flow:
            if f'{c}_sup' in merged.columns:
                merged[c] = merged[c].fillna(0) + merged[f'{c}_sup'].fillna(0)
                merged.drop(columns=[f'{c}_sup'], inplace=True)
        out = merged
    return out
