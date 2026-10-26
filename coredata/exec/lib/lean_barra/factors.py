#!/usr/bin/env python3
"""Style factor names and legacy entry point (delegates to barra_descriptors)."""

from .barra_descriptors import cap_weighted_market_returns, compute_symbol_descriptors

CORE_STYLE_FACTORS = ('size', 'value', 'momentum', 'volatility', 'liquidity')

EXTENDED_STYLE_FACTORS = (
    'beta',
    'strevrsl',
    'ltrevrsl',
    'onerevrsl',
    'midcap',
    'earnyild',
    'divyild',
    'growth',
    'leverage',
    'profit',
    'indmom',
    'dwnrisk',
    'season',
    'regmom',
)

STYLE_FACTORS = CORE_STYLE_FACTORS + EXTENDED_STYLE_FACTORS


def compute_raw_factors(metrics, **kwargs):
    """Compute Barra-style descriptors (see ``barra_descriptors.py``)."""
    date_col = kwargs.get('date_col', 'date')
    mkt = cap_weighted_market_returns(metrics, date_col)
    return compute_symbol_descriptors(metrics, mkt, **kwargs)
