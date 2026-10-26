#!/usr/bin/env python3
"""Industry intercept and ESTU flags for Lean Barra risk model files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import DEFAULT_UNIVERSE
from .barra_ind_map import attach_barra_industry_exposures
from .risk_model import INTERCEPT_FACTOR, attach_official_style_aliases


def load_universe_meta(universe_path: Path | None = None) -> pd.DataFrame:
    p = universe_path or DEFAULT_UNIVERSE
    df = pd.read_csv(p)
    sym_col = 'Symbol' if 'Symbol' in df.columns else 'symbol'
    out = df.rename(columns={sym_col: 'symbol'})
    if 'Sector' in out.columns:
        out['sector'] = out['Sector']
    if 'Industry' in out.columns:
        out['industry'] = out['Industry']
    keep = ['symbol', 'sector', 'industry', 'Market Cap']
    keep = [c for c in keep if c in out.columns]
    return out[keep].drop_duplicates('symbol')


def attach_country_intercept(exposures: pd.DataFrame) -> pd.DataFrame:
    out = exposures.copy()
    out[INTERCEPT_FACTOR] = 1.0
    return out


def estu_mask(
    cap: pd.Series,
    liquidity: pd.Series | None = None,
    *,
    min_cap: float = 2e9,
    estu_pct: float = 0.42,
) -> pd.Series:
    """Return boolean ESTU mask from cap and optional liquidity score."""
    cap = cap.fillna(0).astype(float)
    if liquidity is not None and liquidity.notna().any():
        liq = np.exp(liquidity.fillna(liquidity.median()))
    else:
        liq = pd.Series(1.0, index=cap.index)
    score = np.sqrt(cap.clip(lower=0)) * liq
    cap_ok = cap >= min_cap
    ranked = score.rank(pct=True, ascending=True)
    mask = cap_ok & (ranked >= (1.0 - estu_pct))
    if mask.sum() < max(50, int(0.3 * len(cap))):
        n = max(50, int(0.7 * len(cap)))
        mask = pd.Series(False, index=cap.index)
        mask.loc[score.nlargest(n).index] = True
    return mask


def attach_estu_panel(
    panel: pd.DataFrame,
    *,
    date_col: str = 'date',
    min_cap: float = 2e9,
    estu_pct: float = 0.42,
) -> pd.Series:
    """Per-date ESTU flags on a multi-day metrics panel (before cross-section)."""
    liq_col = 'raw_liquidity' if 'raw_liquidity' in panel.columns else None
    flags = pd.Series(0, index=panel.index, dtype=int)
    for _, g in panel.groupby(date_col, sort=False):
        cap = g.get('market_cap', g.get('capitalization', pd.Series(0.0, index=g.index)))
        liq = g[liq_col] if liq_col else None
        flags.loc[g.index] = estu_mask(cap, liq, min_cap=min_cap, estu_pct=estu_pct).astype(int)
    return flags


def attach_estu(
    exposures: pd.DataFrame,
    *,
    min_cap: float = 2e9,
    estu_pct: float = 0.85,
) -> pd.DataFrame:
    """
    ESTU proxy: liquid large-cap names used for factor-return estimation.

    Flags names above ``min_cap`` that rank in the top ``estu_pct`` by
    ``sqrt(cap) * exp(raw_liquidity)`` (Barra-style liquidity emphasis).
    """
    out = exposures.copy()
    cap = out.get('capitalization', out.get('market_cap', pd.Series(0.0, index=out.index)))
    liq = out['raw_liquidity'] if 'raw_liquidity' in out.columns else (
        out['lb_liquidity'] if 'lb_liquidity' in out.columns else None
    )
    style_ok = out.get('lb_momentum', out.get('lb_size', pd.Series(True, index=out.index))).notna()
    mask = estu_mask(cap, liq, min_cap=min_cap, estu_pct=estu_pct) & style_ok
    out['estu'] = mask.astype(int)
    return out


def finalize_lean_risk_model(
    exposures: pd.DataFrame,
    universe_path: Path | None = None,
) -> pd.DataFrame:
    """Attach intercept, Barra industries, official style aliases, and ESTU."""
    out = attach_barra_industry_exposures(exposures, universe_path)
    out = attach_country_intercept(out)
    out = attach_official_style_aliases(out)
    out = attach_estu(out)
    return out
