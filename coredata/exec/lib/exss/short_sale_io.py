#!/usr/bin/env python3
"""Load and normalize exchange short-sale venue files."""

from __future__ import annotations

import pandas as pd

from .paths import ALL_EXCHANGES, FINRA_EXCHANGES, EXPERIMENT_RATIO_BASES, short_sale_path

HEALTHY_EXCHANGES = tuple(c.replace('ratio_', '') for c in EXPERIMENT_RATIO_BASES)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.strip().lower().replace(' ', '_') for c in out.columns]
    renames = {}
    for c in out.columns:
        if c in ('shortvolume', 'short_vol', 'short_volume'):
            renames[c] = 'short_volume'
        elif c in ('totalvolume', 'total_vol', 'totalume', 'total_volume'):
            renames[c] = 'total_volume'
        elif c in ('symbol', 'ticker'):
            renames[c] = 'symbol'
    out = out.rename(columns=renames)
    if 'short_volume' not in out.columns or 'total_volume' not in out.columns:
        raise ValueError(f'Missing short/total volume columns: {list(out.columns)}')
    if 'symbol' not in out.columns and 'sid' in out.columns:
        out['symbol'] = out['sid'].astype(str)
    elif 'symbol' in out.columns:
        out['symbol'] = out['symbol'].astype(str).str.strip().str.upper()
    out['short_volume'] = pd.to_numeric(out['short_volume'], errors='coerce').fillna(0)
    out['total_volume'] = pd.to_numeric(out['total_volume'], errors='coerce').fillna(0)
    return out


def load_venue_day(yyyymmdd: str, exchange: str) -> pd.DataFrame:
    """Load one venue file; return symbol, short_volume, total_volume."""
    path = short_sale_path(yyyymmdd, exchange)
    if not path.exists():
        return pd.DataFrame(columns=['symbol', 'short_volume', 'total_volume'])
    df = pd.read_csv(path, compression='gzip')
    df = _normalize_columns(df)
    if 'symbol' not in df.columns:
        return pd.DataFrame(columns=['symbol', 'short_volume', 'total_volume'])
    out = df.groupby('symbol', as_index=False)[['short_volume', 'total_volume']].sum()
    return out


def load_healthy_ratios(yyyymmdd: str) -> pd.DataFrame:
    """FINRA trio + NYSE FTP venues only (fast path for no-fillna experiment)."""
    frames: dict[str, pd.Series] = {}
    for ex in HEALTHY_EXCHANGES:
        v = load_venue_day(yyyymmdd, ex)
        if v.empty:
            continue
        s = v.set_index('symbol')
        frames[f'ratio_{ex}'] = s['short_volume'] / s['total_volume'].replace(0, pd.NA)
    if not frames:
        return pd.DataFrame(columns=['symbol'])
    out = pd.DataFrame(frames)
    out.index.name = 'symbol'
    return out.reset_index()


def load_all_venues(yyyymmdd: str) -> pd.DataFrame:
    """
    Load all 11 venues for a date; wide format with ratio_{exchange} columns.

    Returns one row per symbol with ratio columns (NaN if venue missing).
    """
    frames: dict[str, pd.Series] = {}
    total_short = pd.Series(dtype=float)
    total_vol = pd.Series(dtype=float)

    for ex in ALL_EXCHANGES:
        v = load_venue_day(yyyymmdd, ex)
        if v.empty:
            continue
        s = v.set_index('symbol')
        ratio = s['short_volume'] / s['total_volume'].replace(0, pd.NA)
        frames[f'ratio_{ex}'] = ratio
        total_short = total_short.add(s['short_volume'], fill_value=0)
        total_vol = total_vol.add(s['total_volume'], fill_value=0)

    if not frames:
        return pd.DataFrame()

    out = pd.DataFrame(frames)
    out.index.name = 'symbol'
    out = out.reset_index()
    if not total_vol.empty:
        all_ratio = total_short / total_vol.replace(0, pd.NA)
        out['ratio_all'] = out['symbol'].map(all_ratio)
    else:
        out['ratio_all'] = pd.NA
    return out


def venues_present(yyyymmdd: str) -> list[str]:
    return [ex for ex in ALL_EXCHANGES if short_sale_path(yyyymmdd, ex).exists()]
