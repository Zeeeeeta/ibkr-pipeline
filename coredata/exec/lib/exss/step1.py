#!/usr/bin/env python3
"""EXSS step1: T-1 short ratios + equ/barra/locates joins."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from ..opcl.calendar import load_trading_days
from .barra_io import STYLE_COLS, barra_styles
from .equ_stats import avg_dollar_volume_21d, annualized_var, load_univ_symbols, prev_close_adj
from .locates_io import attach_borrow
from .paths import RATIO_BASE_COLS, step1_path
from .short_sale_io import load_all_venues
from .sid_map import attach_sid


def t_minus_1_trading(for_date: str) -> str:
    days = load_trading_days('20150101', for_date, feature_fallback=False)
    prior = [d for d in days if d < for_date]
    if prior:
        return prior[-1]
    dt = datetime.strptime(for_date, '%Y%m%d') - timedelta(days=1)
    return dt.strftime('%Y%m%d')


def build_step1(for_date: str) -> pd.DataFrame:
    load_date = t_minus_1_trading(for_date)
    ratios = load_all_venues(load_date)
    if ratios.empty:
        return pd.DataFrame()

    ratios = attach_sid(ratios)
    univ = load_univ_symbols(for_date)
    if univ:
        ratios = ratios.loc[ratios['symbol'].isin(univ)].copy()

    ratios['quote_ymd'] = for_date
    ratios['is_stock'] = True

    sym = ratios['symbol']
    ratios['close_adj_prv_1'] = prev_close_adj(sym, for_date)
    ratios['avg_dollar_volume_21d'] = avg_dollar_volume_21d(sym, for_date)
    ratios['annualized_var'] = annualized_var(sym, for_date)

    prev_d = t_minus_1_trading(load_date)
    ratios = attach_borrow(ratios, for_date, prev_date=prev_d)

    barra = barra_styles(for_date)
    if not barra.empty:
        ratios = ratios.merge(barra, on='symbol', how='left', suffixes=('', '_barra'))
    else:
        for c in STYLE_COLS:
            if c not in ratios.columns:
                ratios[c] = pd.NA

    for c in RATIO_BASE_COLS:
        if c not in ratios.columns:
            ratios[c] = pd.NA

    return ratios


def write_step1(for_date: str) -> pd.DataFrame:
    df = build_step1(for_date)
    if df.empty:
        return df
    path = step1_path(for_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df
