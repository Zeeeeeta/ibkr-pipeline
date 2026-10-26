#!/usr/bin/env python3
"""Borrow rate from locates (pilot default 0)."""

from __future__ import annotations

import pandas as pd

from ..opcl.paths import LOCATES


def load_borrow_rate(for_date: str) -> pd.Series:
    for name in (
        f'{for_date}.locates_us_multi_prime.rev.csv.gz',
        f'{for_date}.locates.rev.csv.gz',
    ):
        p = LOCATES / for_date[:4] / name
        if p.exists():
            df = pd.read_csv(p, compression='gzip')
            sym_col = 'symbol' if 'symbol' in df.columns else 'ticker'
            if sym_col in df.columns and 'fee_rate' in df.columns:
                out = df.groupby(sym_col)['fee_rate'].min()
                out.index = out.index.astype(str).str.upper()
                return out
    return pd.Series(dtype=float)


def attach_borrow(df: pd.DataFrame, for_date: str, prev_date: str | None = None) -> pd.DataFrame:
    out = df.copy()
    br = load_borrow_rate(for_date)
    if prev_date:
        br_prev = load_borrow_rate(prev_date)
    else:
        br_prev = pd.Series(dtype=float)
    sym = out['symbol'].astype(str).str.upper()
    out['borrow_rate'] = sym.map(br).fillna(0.0)
    out['borrow_rate_prev'] = sym.map(br_prev).fillna(0.0)
    return out
