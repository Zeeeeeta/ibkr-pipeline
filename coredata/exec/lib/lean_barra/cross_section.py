#!/usr/bin/env python3
"""Cross-sectional MAD winsorization and z-score standardization."""

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826


def mad_clip(series: pd.Series, n_mad: float = 3.0) -> pd.Series:
    """Clip outliers using median absolute deviation (Barra-style)."""
    s = series.astype(float)
    valid = s.dropna()
    if valid.empty:
        return s
    med = valid.median()
    mad = (valid - med).abs().median()
    if mad == 0 or np.isnan(mad):
        return s
    spread = n_mad * MAD_SCALE * mad
    lo, hi = med - spread, med + spread
    return s.clip(lo, hi)


def cross_section_zscore(series: pd.Series) -> pd.Series:
    """Z-score a single-day cross-section (mean=0, std=1)."""
    s = series.astype(float)
    m = s.mean()
    sd = s.std(ddof=0)
    if sd == 0 or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - m) / sd


def _estu_stats(series: pd.Series, estu: pd.Series) -> tuple[float, float, float, float]:
    """Return (median, mad, mean, std) using ESTU subset when available."""
    s = series.astype(float)
    mask = estu.astype(bool) if estu is not None else pd.Series(True, index=s.index)
    estu_s = s[mask & s.notna()]
    if estu_s.empty or len(estu_s) < 5:
        estu_s = s.dropna()
    if estu_s.empty:
        return 0.0, 0.0, 0.0, 0.0
    med = float(estu_s.median())
    mad = float((estu_s - med).abs().median())
    m = float(estu_s.mean())
    sd = float(estu_s.std(ddof=0))
    return med, mad, m, sd


def mad_clip_estu(series: pd.Series, estu: pd.Series, n_mad: float = 3.0) -> pd.Series:
    """MAD winsorization using ESTU (estimation universe) distribution."""
    s = series.astype(float)
    med, mad, _, _ = _estu_stats(s, estu)
    if mad == 0 or np.isnan(mad):
        return s
    spread = n_mad * MAD_SCALE * mad
    lo, hi = med - spread, med + spread
    return s.clip(lo, hi)


def cross_section_zscore_estu(series: pd.Series, estu: pd.Series) -> pd.Series:
    """Z-score using ESTU mean/std, applied to the full cross-section."""
    s = series.astype(float)
    _, _, m, sd = _estu_stats(s, estu)
    if sd == 0 or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - m) / sd


def cap_weighted_orthogonalize(
    y: pd.Series,
    x: pd.Series,
    cap: pd.Series,
) -> pd.Series:
    """Regression-weighted residual of y after projecting on x (Barra midcap step)."""
    yv = y.astype(float).values
    xv = x.astype(float).values
    w = np.sqrt(np.clip(cap.astype(float).values, 1.0, None))
    mask = np.isfinite(yv) & np.isfinite(xv) & np.isfinite(w)
    if mask.sum() < 3:
        return y
    sw = np.sqrt(w[mask])
    X = np.column_stack([np.ones(mask.sum()), xv[mask]]) * sw[:, None]
    yw = yv[mask] * sw
    beta, _, _, _ = np.linalg.lstsq(X, yw, rcond=None)
    fit = X @ beta
    resid = yv.copy()
    resid[mask] = yw - fit.ravel()
    return pd.Series(resid, index=y.index)


def apply_midcap_exposure(
    df: pd.DataFrame,
    *,
    date_col: str = 'date',
    cap_col: str = 'capitalization',
    size_col: str = 'lb_size',
    out_col: str = 'lb_midcap',
    mad_multiplier: float = 3.0,
) -> pd.DataFrame:
    """
    MIDCAP: cube standardized size, orthogonalize to size, MAD + z-score.

    Per Barra Descriptor Details (Mar 2015).
    """
    out = df.copy()
    use_estu = 'estu' in out.columns

    def _mid_day(g: pd.DataFrame) -> pd.DataFrame:
        day = g.copy()
        cap = g.get(cap_col, g.get('market_cap', 1.0))
        mid_raw = cap_weighted_orthogonalize(day[size_col] ** 3, day[size_col], cap)
        estu = day['estu'] if use_estu else pd.Series(True, index=day.index)
        clipped = mad_clip_estu(mid_raw, estu, n_mad=mad_multiplier) if use_estu else mad_clip(
            mid_raw, n_mad=mad_multiplier
        )
        day[out_col] = cross_section_zscore_estu(clipped, estu) if use_estu else cross_section_zscore(clipped)
        return day

    pieces = []
    for date_val, g in out.groupby(date_col, sort=False):
        day = _mid_day(g)
        if date_col not in day.columns:
            day[date_col] = date_val
        pieces.append(day)
    return pd.concat(pieces, ignore_index=True)


def cleanse_factor_cross_section(
    df: pd.DataFrame,
    raw_cols: list[str],
    *,
    date_col: str = 'date',
    estu_col: str | None = 'estu',
    mad_multiplier: float = 3.0,
    out_prefix: str = 'lb_',
) -> pd.DataFrame:
    """
    Per trading day: MAD clip then z-score each raw factor column.

    When ``estu_col`` is present, winsorization and z-scoring use the ESTU
    subset (Barra estimation universe), then apply those stats to all names.

    Adds standardized columns ``{out_prefix}{factor}`` (e.g. ``lb_size``).
    """
    out = df.copy()
    use_estu = estu_col is not None and estu_col in out.columns

    def _cleanse_day(g: pd.DataFrame) -> pd.DataFrame:
        day = g.copy()
        estu = day[estu_col] if use_estu else pd.Series(True, index=day.index)
        for raw_col in raw_cols:
            factor = raw_col.removeprefix('raw_')
            out_col = f'{out_prefix}{factor}'
            s = day[raw_col]
            clipped = mad_clip_estu(s, estu, n_mad=mad_multiplier) if use_estu else mad_clip(s, n_mad=mad_multiplier)
            day[out_col] = cross_section_zscore_estu(clipped, estu) if use_estu else cross_section_zscore(clipped)
        return day

    pieces = []
    for date_val, g in out.groupby(date_col, sort=False):
        day = _cleanse_day(g)
        if date_col not in day.columns:
            day[date_col] = date_val
        pieces.append(day)
    return pd.concat(pieces, ignore_index=True)
