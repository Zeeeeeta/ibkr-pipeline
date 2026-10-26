#!/usr/bin/env python3
"""Official USFASTD factor name lists (for column classification)."""

import pandas as pd

# 24 style factors in prod ``usfastd_rsk.rev.mk4`` files.
OFFICIAL_STYLE_FACTORS = (
    'usfastd_1drevrsl',
    'usfastd_beta',
    'usfastd_divyild',
    'usfastd_dwnrisk',
    'usfastd_earnqlty',
    'usfastd_earnyild',
    'usfastd_growth',
    'usfastd_indmom',
    'usfastd_leverage',
    'usfastd_liquidty',
    'usfastd_ltrevrsl',
    'usfastd_mgmtqlty',
    'usfastd_midcap',
    'usfastd_momentum',
    'usfastd_profit',
    'usfastd_prospect',
    'usfastd_regmom',
    'usfastd_resvol',
    'usfastd_season',
    'usfastd_sentmt',
    'usfastd_shortint',
    'usfastd_size',
    'usfastd_strevrsl',
    'usfastd_value',
)

INTERCEPT_FACTOR = 'usfastd_country'

LEAN_STYLE_PREFIX = 'lb_'
LEAN_INDUSTRY_PREFIX = 'lb_ind_'

DEFAULT_RETURN_CLIP = (-0.2, 0.2)
DEFAULT_REMOVE_INDUSTRY_IDX = 0

# Lean ``lb_*`` -> official USFASTD style column names.
LEAN_TO_OFFICIAL_STYLE = {
    'lb_onerevrsl': 'usfastd_1drevrsl',
    'lb_beta': 'usfastd_beta',
    'lb_divyild': 'usfastd_divyild',
    'lb_dwnrisk': 'usfastd_dwnrisk',
    'lb_earnyild': 'usfastd_earnyild',
    'lb_growth': 'usfastd_growth',
    'lb_indmom': 'usfastd_indmom',
    'lb_leverage': 'usfastd_leverage',
    'lb_liquidity': 'usfastd_liquidty',
    'lb_ltrevrsl': 'usfastd_ltrevrsl',
    'lb_midcap': 'usfastd_midcap',
    'lb_momentum': 'usfastd_momentum',
    'lb_profit': 'usfastd_profit',
    'lb_regmom': 'usfastd_regmom',
    'lb_volatility': 'usfastd_resvol',
    'lb_season': 'usfastd_season',
    'lb_size': 'usfastd_size',
    'lb_strevrsl': 'usfastd_strevrsl',
    'lb_value': 'usfastd_value',
}

# Styles we cannot yet proxy (left at 0 in official alias columns).
UNMODELED_OFFICIAL_STYLES = (
    'usfastd_earnqlty',
    'usfastd_mgmtqlty',
    'usfastd_prospect',
    'usfastd_sentmt',
    'usfastd_shortint',
)


def attach_official_style_aliases(exposures: pd.DataFrame) -> pd.DataFrame:
    """Copy ``lb_*`` z-scores to ``usfastd_*`` columns for prod-compatible residualization."""
    out = exposures.copy()
    for lb_col, official in LEAN_TO_OFFICIAL_STYLE.items():
        if lb_col in out.columns:
            out[official] = out[lb_col]
    for col in UNMODELED_OFFICIAL_STYLES:
        if col not in out.columns:
            out[col] = 0.0
    return out
