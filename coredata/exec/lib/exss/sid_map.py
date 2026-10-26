#!/usr/bin/env python3
"""Symbol ↔ Barra sid mapping from mk4 files."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..lean_barra.mk4_loader import load_mk4
from ..opcl.paths import BARRA
from .paths import SID_MAP_PATH


def _iter_mk4_files() -> list[Path]:
    if not BARRA.exists():
        return []
    return sorted(BARRA.glob('*/*.usfastd_rsk.rev.mk4.csv.gz'))


def build_sid_map_from_mk4(*, out_path: Path | None = None) -> pd.DataFrame:
    """Union symbol/sid from all mk4 files on disk."""
    out_path = out_path or SID_MAP_PATH
    rows: dict[str, int] = {}
    for path in _iter_mk4_files():
        df = load_mk4(path)
        if 'symbol' not in df.columns:
            continue
        sid_col = 'tid' if 'tid' in df.columns else 'sid'
        if sid_col not in df.columns:
            continue
        for _, row in df.iterrows():
            sym = str(row.get('symbol', '')).strip().upper()
            if not sym or sym in ('NAN', 'NONE'):
                continue
            try:
                rows[sym] = int(row[sid_col])
            except (TypeError, ValueError):
                continue

    result = pd.DataFrame([{'symbol': k, 'sid': v} for k, v in sorted(rows.items())])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False)
    return result


def load_sid_map(path: Path | None = None) -> pd.DataFrame:
    path = path or SID_MAP_PATH
    if path.exists():
        return pd.read_csv(path)
    return build_sid_map_from_mk4(out_path=path)


def attach_sid(df: pd.DataFrame, sid_map: pd.DataFrame | None = None) -> pd.DataFrame:
    out = df.copy()
    sm = sid_map if sid_map is not None else load_sid_map()
    if sm.empty or 'symbol' not in out.columns:
        out['sid'] = pd.NA
        return out
    m = sm.drop_duplicates('symbol').set_index('symbol')['sid']
    out['symbol'] = out['symbol'].astype(str).str.upper()
    out['sid'] = out['symbol'].map(m)
    return out
