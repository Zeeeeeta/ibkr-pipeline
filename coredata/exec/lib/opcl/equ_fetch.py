#!/usr/bin/env python3
"""Shared helpers for IB equity price backfill into equ_prices."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..paths import DEFAULT_REF_DIR
from .paths import EQU_PRICES
from .calendar import load_trading_days

EQU_BACKFILL_PROGRESS = DEFAULT_REF_DIR / 'equ_backfill_progress.csv'
EQU_OUTPUT_COLS = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'average', 'barCount']


def load_universe_symbols(universe_path: Path | None = None) -> list[str]:
    p = universe_path or DEFAULT_UNIVERSE
    df = pd.read_csv(p)
    col = 'Symbol' if 'Symbol' in df.columns else 'symbol'
    return df[col].dropna().astype(str).str.upper().unique().tolist()


def resolve_history_start(end: str, train_years: float | None, start: str | None) -> str:
    if train_years is None:
        if not start:
            raise ValueError('Provide start or train_years')
        return start
    days = load_trading_days('19900101', end, feature_fallback=False)
    if not days:
        y = int(end[:4]) - int(train_years)
        return f'{y}{end[4:]}'
    anchor = end if end in days else days[-1]
    idx = days.index(anchor)
    n = max(1, int(train_years * 252))
    return days[max(0, idx - n)]


def write_equ_day(ymd: str, grp: pd.DataFrame) -> None:
    path = EQU_PRICES / ymd[:4] / f'{ymd}.equ_prices.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    out = grp[EQU_OUTPUT_COLS].copy()
    if path.exists():
        existing = pd.read_csv(path)
        combined = pd.concat([existing, out], ignore_index=True)
        combined = combined.drop_duplicates('symbol', keep='last')
    else:
        combined = out
    combined.to_csv(path, index=False)


def write_symbol_panel(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    for ymd, grp in df.groupby('date'):
        write_equ_day(str(ymd), grp)
    return int(df['date'].nunique())


def load_backfill_progress(path: Path | None = None) -> pd.DataFrame:
    p = path or EQU_BACKFILL_PROGRESS
    if not p.exists():
        return pd.DataFrame(columns=['symbol', 'start', 'end', 'n_days', 'status', 'updated_at'])
    return pd.read_csv(p)


def save_backfill_progress(row: dict, path: Path | None = None) -> None:
    p = path or EQU_BACKFILL_PROGRESS
    p.parent.mkdir(parents=True, exist_ok=True)
    df = load_backfill_progress(p)
    sym = row['symbol']
    df = df[df['symbol'] != sym] if not df.empty else df
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(p, index=False)


def symbol_backfill_complete(
    symbol: str,
    start: str,
    end: str,
    *,
    expected_days: int,
    min_ratio: float = 0.92,
    progress: pd.DataFrame | None = None,
) -> bool:
    if progress is not None and not progress.empty:
        hit = progress[(progress['symbol'] == symbol) & (progress['status'] == 'ok')]
        if not hit.empty:
            rec = hit.iloc[-1]
            if str(rec.get('start', '')) <= start and str(rec.get('end', '')) >= end:
                if int(rec.get('n_days', 0)) >= int(expected_days * min_ratio):
                    return True
    probes = [start, end]
    mid_idx = expected_days // 2
    days = load_trading_days(start, end, feature_fallback=False)
    if days:
        probes.append(days[min(mid_idx, len(days) - 1)])
    for d in probes:
        fp = EQU_PRICES / d[:4] / f'{d}.equ_prices.csv'
        if not fp.exists():
            return False
        syms = set(pd.read_csv(fp, usecols=['symbol'])['symbol'].astype(str))
        if symbol not in syms:
            return False
    return False
