#!/usr/bin/env python3
"""End-to-end Lean Barra exposure pipeline."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import DEFAULT_REF_DIR, DEFAULT_UNIVERSE
from .barra_descriptors import cap_weighted_market_returns, compute_symbol_descriptors
from .cross_section import apply_midcap_exposure, cleanse_factor_cross_section
from .factors import STYLE_FACTORS
from .ingest import (
    build_metrics_from_equ_prices,
    load_metrics_dataframe,
    load_or_fetch_fundamentals,
    load_symbol_sid,
    load_universe_symbols,
)
from .industry import attach_estu_panel, finalize_lean_risk_model
from .paths import exposures_csv_path, exposures_path

RAW_FACTOR_COLS = [f'raw_{f}' for f in STYLE_FACTORS]
EXPOSURE_COLS = [f'lb_{f}' for f in STYLE_FACTORS]


def run_lean_barra(
    metrics: pd.DataFrame,
    *,
    date_col: str = 'date',
    mad_multiplier: float = 3.0,
) -> pd.DataFrame:
    """Steps 1–2: Barra descriptors + cross-sectional MAD clip and z-score."""
    metrics = load_metrics_dataframe(metrics)
    # First pass: descriptors + ESTU proxy for cap-weighted market returns.
    mkt_full = cap_weighted_market_returns(metrics, date_col, estu_col=None)
    raw = compute_symbol_descriptors(metrics, mkt_full, date_col=date_col)
    raw['estu'] = attach_estu_panel(raw, date_col=date_col)
    mkt = cap_weighted_market_returns(raw, date_col, estu_col='estu')
    raw = compute_symbol_descriptors(raw.drop(columns=['estu'], errors='ignore'), mkt, date_col=date_col)
    raw['estu'] = attach_estu_panel(raw, date_col=date_col)

    # Fill remaining style slots from fundamentals when present.
    for col, raw_col in (
        ('dividend_yield', 'raw_divyild'),
        ('debt_to_equity', 'raw_leverage'),
        ('roe', 'raw_profit'),
        ('eps_growth', 'raw_growth'),
    ):
        if col in raw.columns and raw_col not in raw.columns:
            raw[raw_col] = raw[col].astype(float)

    if 'sector' in raw.columns and 'raw_indmom' not in raw.columns:
        raw['raw_indmom'] = raw['raw_momentum'] - raw.groupby([date_col, 'sector'])['raw_momentum'].transform('median')
    if 'raw_regmom' not in raw.columns:
        raw['raw_regmom'] = raw['raw_momentum']
    if 'raw_dwnrisk' not in raw.columns and 'raw_volatility' in raw.columns:
        raw['raw_dwnrisk'] = raw['raw_volatility']
    if 'raw_season' not in raw.columns:
        dt = pd.to_datetime(raw[date_col].astype(str), format='%Y%m%d', errors='coerce')
        raw['raw_season'] = np.cos(2 * np.pi * dt.dt.month.fillna(6) / 12.0)

    for f in STYLE_FACTORS:
        c = f'raw_{f}'
        if c not in raw.columns:
            raw[c] = np.nan

    midcap_cols = [c for c in RAW_FACTOR_COLS if c != 'raw_midcap']
    out = cleanse_factor_cross_section(
        raw,
        midcap_cols,
        date_col=date_col,
        estu_col='estu',
        mad_multiplier=mad_multiplier,
    )
    cap = out.get('capitalization', out.get('market_cap', 1.0))
    out['capitalization'] = cap
    return apply_midcap_exposure(out, date_col=date_col, mad_multiplier=mad_multiplier)


def attach_sid(exposures: pd.DataFrame, ref_dir: Path | None = None) -> pd.DataFrame:
    sid_map = load_symbol_sid(ref_dir)
    if sid_map.empty:
        exposures = exposures.copy()
        exposures['sid'] = exposures['symbol']
        return exposures
    return exposures.merge(sid_map, on='symbol', how='left')


def build_daily_exposures(
    for_date: str,
    *,
    universe_path: Path | None = None,
    ref_dir: Path | None = None,
    price_history_days: int = 1100,
    fmp_api_key: str | None = None,
    mad_multiplier: float = 3.0,
) -> pd.DataFrame:
    """
    Build standardized style exposures for one trade date.

    Uses up to ``price_history_days`` of local equity EOD history ending on
    ``for_date`` (walks back over available files).
    """
    from datetime import datetime, timedelta

    universe_path = universe_path or DEFAULT_UNIVERSE
    symbols = load_universe_symbols(universe_path)
    end = for_date
    start_dt = datetime.strptime(for_date, '%Y%m%d') - timedelta(days=int(price_history_days * 1.5))
    start = start_dt.strftime('%Y%m%d')

    fundamentals = load_or_fetch_fundamentals(symbols, api_key=fmp_api_key, as_of=for_date)
    metrics = build_metrics_from_equ_prices(
        symbols,
        start,
        end,
        universe_path=universe_path,
        fundamentals=fundamentals if not fundamentals.empty else None,
    )
    if metrics.empty:
        return pd.DataFrame()

    from .industry import load_universe_meta

    meta = load_universe_meta(universe_path)
    sector_col = 'sector' if 'sector' in meta.columns else 'Sector'
    if sector_col in meta.columns:
        metrics = metrics.merge(
            meta[['symbol', sector_col]].rename(columns={sector_col: 'sector'}),
            on='symbol',
            how='left',
        )

    day_metrics = metrics[metrics['date'] <= for_date].copy()
    exposures = run_lean_barra(day_metrics, mad_multiplier=mad_multiplier)
    exposures = exposures[exposures['date'] == for_date].copy()
    exposures = attach_sid(exposures, ref_dir or DEFAULT_REF_DIR)
    if 'market_cap' in exposures.columns:
        exposures['capitalization'] = exposures['market_cap']
    exposures = finalize_lean_risk_model(exposures, universe_path)
    return exposures.reset_index(drop=True)


def write_exposures(
    exposures: pd.DataFrame,
    for_date: str,
    *,
    write_csv: bool = True,
) -> Path:
    out = exposures_path(for_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    exposures.to_parquet(out, index=False)
    if write_csv:
        csv_out = exposures_csv_path(for_date)
        exposures.to_csv(csv_out, index=False, compression='gzip')
    return out


def load_exposures(for_date: str) -> pd.DataFrame:
    p = exposures_path(for_date)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)
