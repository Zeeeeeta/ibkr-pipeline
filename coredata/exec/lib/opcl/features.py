#!/usr/bin/env python3
"""Load OPCL feature parquets."""

from __future__ import annotations

import pandas as pd

from .paths import FEATURES_OUT


def load_features(ymd: str) -> pd.DataFrame:
    p = FEATURES_OUT / ymd[:4] / f'{ymd}.opcl.parq'
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df['quote_ymd'] = ymd
    return df


def load_feature_stack(dates: list[str]) -> pd.DataFrame:
    frames = [load_features(d) for d in dates]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if 'zscore' in c or c.endswith('_5day')]
