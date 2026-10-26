#!/usr/bin/env python3
"""Map universe Industry strings to Barra ``usfastd_*`` industry factor columns."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..paths import DEFAULT_REF_DIR

KEYWORDS_PATH = DEFAULT_REF_DIR / 'barra_industry_keywords.csv'
FALLBACK_INDUSTRY = 'usfastd_misc'


def load_industry_keywords(path: Path | None = None) -> pd.DataFrame:
    p = path or KEYWORDS_PATH
    if not p.exists():
        return pd.DataFrame(columns=['barra_industry', 'keyword'])
    return pd.read_csv(p)


def all_barra_industries(path: Path | None = None) -> list[str]:
    kw = load_industry_keywords(path)
    if kw.empty:
        return [FALLBACK_INDUSTRY]
    inds = sorted(kw['barra_industry'].unique().tolist())
    if FALLBACK_INDUSTRY not in inds:
        inds.append(FALLBACK_INDUSTRY)
    return inds


def map_industry_label(label: str, keywords: pd.DataFrame | None = None) -> str:
    """Keyword match universe Industry / Sector text to a Barra industry slug."""
    kw = keywords if keywords is not None else load_industry_keywords()
    text = str(label or '').strip().lower()
    if not text or kw.empty:
        return FALLBACK_INDUSTRY
    for _, row in kw.iterrows():
        if str(row['keyword']).lower() in text:
            return str(row['barra_industry'])
    return FALLBACK_INDUSTRY


def attach_barra_industry_exposures(
    exposures: pd.DataFrame,
    universe_path: Path | None = None,
    *,
    keywords_path: Path | None = None,
) -> pd.DataFrame:
    """
    One-hot Barra industry factors (``usfastd_*``, ~60 columns).

    Each stock maps to a single primary industry (weight 1.0). Prod assigns up
    to five weighted industries; this is a deliberate simplification.
    """
    from ..paths import DEFAULT_UNIVERSE
    from .industry import load_universe_meta

    meta = load_universe_meta(universe_path or DEFAULT_UNIVERSE)
    keywords = load_industry_keywords(keywords_path)
    industries = all_barra_industries(keywords_path)

    cols = ['symbol']
    for c in ('industry', 'sector', 'Industry', 'Sector'):
        if c in meta.columns:
            cols.append(c)
    merged = exposures.merge(meta[cols], on='symbol', how='left')
    ind = merged.get('industry', merged.get('Industry'))
    sec = merged.get('sector', merged.get('Sector'))
    label = ind.fillna(sec) if ind is not None else sec
    merged['barra_industry'] = label.apply(lambda s: map_industry_label(s, keywords))

    for ind in industries:
        merged[ind] = (merged['barra_industry'] == ind).astype(float)

    drop_cols = [
        c for c in merged.columns
        if c in ('Industry', 'Sector', 'industry', 'sector', 'barra_industry')
    ]
    return merged.drop(columns=drop_cols)
