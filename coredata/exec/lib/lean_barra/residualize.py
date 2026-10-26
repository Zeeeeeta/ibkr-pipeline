#!/usr/bin/env python3
"""
Prod-aligned Barra residualization (``ResRtnHelperQbt`` replica).

Estimates factor returns via simultaneous weighted GLS on the ESTU subset::

    R_factor = (B^T W B)^{-1} B^T W R_raw

then applies ``res_rtn = R_raw - B_full @ R_factor`` to all names.

Matches prod on:
- sqrt(capitalization) regression weights
- return pre-clipping to (-0.2, 0.2) before estimation
- simultaneous (not sequential) factor solve
- industry-neutral constraint (one industry removed, return imputed)
- ESTU-only factor estimation, residuals on full universe
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .factors import STYLE_FACTORS
from .barra_ind_map import all_barra_industries
from .risk_model import (
    DEFAULT_REMOVE_INDUSTRY_IDX,
    DEFAULT_RETURN_CLIP,
    INTERCEPT_FACTOR,
    LEAN_INDUSTRY_PREFIX,
    LEAN_STYLE_PREFIX,
    OFFICIAL_STYLE_FACTORS,
)


@dataclass
class FactorSpec:
    intercept_col: str | None
    style_cols: list[str]
    industry_cols: list[str]
    remove_industry_idx: int = DEFAULT_REMOVE_INDUSTRY_IDX

    @property
    def all_cols(self) -> list[str]:
        cols = []
        if self.intercept_col:
            cols.append(self.intercept_col)
        cols.extend(self.style_cols)
        cols.extend(self.industry_cols)
        return cols

    @property
    def n_non_industry(self) -> int:
        n = len(self.style_cols)
        if self.intercept_col:
            n += 1
        return n


def classify_factor_columns(risk_model: pd.DataFrame) -> FactorSpec:
    """Detect intercept, style, and industry columns from official or Lean files."""
    cols = set(risk_model.columns)
    intercept = INTERCEPT_FACTOR if INTERCEPT_FACTOR in cols else None

    official_styles = [c for c in OFFICIAL_STYLE_FACTORS if c in cols]
    lean_styles = sorted(
        c for c in cols
        if c.startswith(LEAN_STYLE_PREFIX) and not c.startswith(LEAN_INDUSTRY_PREFIX)
    )
    style_cols = official_styles if official_styles else lean_styles

    known_inds = set(all_barra_industries())
    industry_cols = sorted(c for c in cols if c in known_inds)
    if not industry_cols:
        industry_cols = sorted(
            c for c in cols
            if c.startswith('usfastd_')
            and c not in style_cols
            and c != INTERCEPT_FACTOR
            and c not in OFFICIAL_STYLE_FACTORS
        )
    if not industry_cols:
        industry_cols = sorted(c for c in cols if c.startswith(LEAN_INDUSTRY_PREFIX))

    return FactorSpec(
        intercept_col=intercept,
        style_cols=style_cols,
        industry_cols=industry_cols,
    )


def _sqrt_cap_weights(cap: np.ndarray) -> np.ndarray:
    w = np.sqrt(np.clip(cap.astype(float), 1.0, None))
    w = np.where(np.isfinite(w), w, 1.0)
    return w


def _estu_mask(risk_model: pd.DataFrame, valid_y: np.ndarray) -> np.ndarray:
    if 'estu' in risk_model.columns:
        estu = risk_model['estu'].fillna(0).astype(int).values == 1
    else:
        estu = np.ones(len(risk_model), dtype=bool)
    return estu & np.isfinite(valid_y)


def _industry_cap_weights(
    B_ind: np.ndarray,
    cap: np.ndarray,
    remove_idx: int,
) -> np.ndarray:
    """Cap-weighted industry weights for the neutral constraint (non-removed)."""
    if B_ind.size == 0:
        return np.array([])
    ind_caps = (B_ind * cap.reshape(-1, 1)).sum(axis=0)
    keep = [j for j in range(B_ind.shape[1]) if j != remove_idx]
    w = ind_caps[keep]
    total = w.sum()
    if total <= 0:
        return np.ones(len(keep)) / max(len(keep), 1)
    return w / total


def _build_estimation_matrix(
    B_full: np.ndarray,
    spec: FactorSpec,
) -> tuple[np.ndarray, int]:
    """Drop one industry column for identification."""
    if not spec.industry_cols:
        return B_full, -1
    remove_idx = min(spec.remove_industry_idx, len(spec.industry_cols) - 1)
    n_non = spec.n_non_industry
    keep = list(range(n_non)) + [n_non + j for j in range(len(spec.industry_cols)) if j != remove_idx]
    return B_full[:, keep], remove_idx


def estimate_factor_returns(
    raw_returns: np.ndarray,
    risk_model: pd.DataFrame,
    *,
    spec: FactorSpec | None = None,
    return_clip: tuple[float, float] = DEFAULT_RETURN_CLIP,
    cap_col: str = 'capitalization',
) -> tuple[np.ndarray, FactorSpec]:
    """
    Simultaneous GLS factor return estimation on ESTU (``ResRtnHelperQbt`` core).
    """
    spec = spec or classify_factor_columns(risk_model)
    y = np.asarray(raw_returns, dtype=float)
    lo, hi = return_clip
    y_clip = np.clip(y, lo, hi)

    cap = risk_model.get(cap_col, pd.Series(1.0, index=risk_model.index)).fillna(1.0).values
    w = _sqrt_cap_weights(cap)
    estu = _estu_mask(risk_model, y_clip)

    if estu.sum() < spec.n_non_industry + 2:
        return np.zeros(len(spec.all_cols)), spec

    B_full = risk_model[spec.all_cols].fillna(0.0).values.astype(float)
    B_est, removed_idx = _build_estimation_matrix(B_full[estu], spec)

    y_est = y_clip[estu]
    w_est = w[estu]
    W = np.diag(w_est)

    BtW = B_est.T @ W
    BtWB = BtW @ B_est
    try:
        BtWB_inv = np.linalg.pinv(BtWB)
    except np.linalg.LinAlgError:
        return np.zeros(len(spec.all_cols)), spec

    factor_rtn_est = BtWB_inv @ BtW @ y_est

    if not spec.industry_cols or removed_idx < 0:
        return factor_rtn_est, spec

    n_non = spec.n_non_industry
    removed_full_idx = n_non + removed_idx
    factor_rtn = np.insert(factor_rtn_est, removed_full_idx, 0.0)

    B_ind = B_full[estu, n_non:n_non + len(spec.industry_cols)]
    ind_cap_w = _industry_cap_weights(B_ind, cap[estu], removed_idx)
    other_ind_rtns = np.delete(factor_rtn[n_non:n_non + len(spec.industry_cols)], removed_idx)
    factor_rtn[removed_full_idx] = -float(other_ind_rtns @ ind_cap_w)

    return factor_rtn, spec


def residualize_returns(
    raw_returns: pd.Series,
    risk_model: pd.DataFrame,
    *,
    return_clip: tuple[float, float] = DEFAULT_RETURN_CLIP,
    cap_col: str = 'capitalization',
) -> pd.Series:
    """
    ``res_rtn = R_raw - B_full @ R_factor`` for all rows in ``risk_model``.

    ``raw_returns`` must align with ``risk_model.index``.
    """
    y = raw_returns.reindex(risk_model.index)
    factor_rtn, spec = estimate_factor_returns(
        y.values,
        risk_model,
        return_clip=return_clip,
        cap_col=cap_col,
    )
    B_full = risk_model[spec.all_cols].fillna(0.0).values.astype(float)
    fitted = B_full @ factor_rtn
    resid = y.values - fitted
    return pd.Series(resid, index=risk_model.index)


def merge_risk_model(
    df: pd.DataFrame,
    risk_model: pd.DataFrame,
) -> pd.DataFrame | None:
    """Join alpha frame to risk model on symbol (preferred) or sid."""
    rm = risk_model.copy()

    def _dedupe(key: str) -> pd.DataFrame:
        if key not in rm.columns:
            return rm
        return rm.drop_duplicates(key, keep='last')

    sym_left = None
    if 'symbol' in df.columns:
        sym_left = 'symbol'
    elif 'underlying_symbol' in df.columns:
        sym_left = 'underlying_symbol'

    if sym_left and 'symbol' in rm.columns:
        r = _dedupe('symbol')
        if sym_left == 'symbol':
            return df.merge(r, on='symbol', how='left', suffixes=('', '_barra'))
        return df.merge(
            r,
            left_on=sym_left,
            right_on='symbol',
            how='left',
            suffixes=('', '_barra'),
        )

    if 'sid' in rm.columns and 'sid' in df.columns:
        sid = rm['sid']
        sid_ok = sid.notna().sum() >= 0.9 * len(rm) and sid.nunique() >= 0.9 * sid.notna().sum()
        if sid_ok:
            r = _dedupe('sid')
            return df.merge(r, on='sid', how='left', suffixes=('', '_barra'))
    return None


def residualize_merged(
    df: pd.DataFrame,
    y_col: str,
    risk_model: pd.DataFrame,
    *,
    return_clip: tuple[float, float] = DEFAULT_RETURN_CLIP,
) -> pd.Series:
    """Residualize ``df[y_col]`` after merging with ``risk_model``; index follows ``df``."""
    orig_index = df.index
    work = df.reset_index(drop=True)
    merged = merge_risk_model(work, risk_model)
    if merged is None:
        return df[y_col]
    valid = merged[y_col].notna()
    out = pd.Series(np.nan, index=orig_index, dtype=float)
    if not valid.any():
        return out

    sub = merged.loc[valid].copy()
    cap_col = 'capitalization' if 'capitalization' in sub.columns else 'market_cap'
    if cap_col not in sub.columns:
        sub['capitalization'] = 1.0
        cap_col = 'capitalization'

    resid = residualize_returns(
        sub[y_col],
        sub,
        return_clip=return_clip,
        cap_col=cap_col,
    )
    out.iloc[sub.index] = resid.reindex(sub.index).values
    return out


def parity_checklist() -> dict[str, dict[str, str]]:
    """Document prod parity for Lean Barra vs ``ResRtnHelperQbt``."""
    from .factors import CORE_STYLE_FACTORS, EXTENDED_STYLE_FACTORS
    from .barra_ind_map import all_barra_industries

    n_styles = len(CORE_STYLE_FACTORS) + len(EXTENDED_STYLE_FACTORS)
    n_inds = len(all_barra_industries())
    return {
        'sqrt_cap_weights': {'prod': 'sqrt(capitalization)', 'lean_barra': 'sqrt(capitalization)', 'match': 'yes'},
        'estimation_method': {'prod': 'simultaneous GLS', 'lean_barra': 'simultaneous GLS', 'match': 'yes'},
        'estu_filter': {
            'prod': 'estu == 1 (~1.5–2k names)',
            'lean_barra': f'top 85% by sqrt(cap)*liquidity, cap>={2e9:.0e}',
            'match': 'partial',
        },
        'return_clip': {'prod': '(-0.2, 0.2)', 'lean_barra': '(-0.2, 0.2)', 'match': 'yes'},
        'industry_neutral': {'prod': 'remove 1 industry, impute return', 'lean_barra': 'same', 'match': 'yes'},
        'full_universe_residual': {'prod': 'B_full @ R_factor on all tids', 'lean_barra': 'same', 'match': 'yes'},
        'style_factor_count': {
            'prod': '24 USFASTD styles',
            'lean_barra': f'{n_styles} lb_* proxies + 5 unmodeled zeros',
            'match': 'partial',
        },
        'industry_factor_count': {
            'prod': '60 Barra industries (multi-weight)',
            'lean_barra': f'{n_inds} keyword-mapped usfastd_* (single primary)',
            'match': 'partial',
        },
        'sequential_regression': {'prod': 'no', 'lean_barra': 'no', 'match': 'yes'},
        'official_column_names': {
            'prod': 'usfastd_* native',
            'lean_barra': 'usfastd_* aliases from lb_*',
            'match': 'yes',
        },
    }
