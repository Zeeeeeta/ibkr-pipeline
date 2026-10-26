#!/usr/bin/env python3
"""Downstream connectors for alpha residualization and portfolio optimization."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .factors import STYLE_FACTORS
from .risk_model import LEAN_INDUSTRY_PREFIX

EXPOSURE_COLS = [f'lb_{f}' for f in STYLE_FACTORS]


def exposure_columns(df: pd.DataFrame, prefix: str = 'lb_') -> list[str]:
    return [
        c for c in df.columns
        if c.startswith(prefix) and not c.startswith(LEAN_INDUSTRY_PREFIX)
    ]


def ols_design_matrix(
    exposures: pd.DataFrame,
    *,
    factor_cols: list[str] | None = None,
    add_constant: bool = True,
) -> tuple[np.ndarray, list[str], pd.Index]:
    """
    Stage A: design matrix for cross-sectional OLS (statsmodels / numpy).

    Returns ``(X, column_names, index)`` aligned to ``exposures`` row order.
    """
    cols = factor_cols or exposure_columns(exposures)
    cols = [c for c in cols if c in exposures.columns]
    X = exposures[cols].fillna(0.0).values.astype(float)
    names = list(cols)
    if add_constant:
        X = np.column_stack([np.ones(len(X)), X])
        names = ['const'] + names
    return X, names, exposures.index


def residualize_alpha(
    y: pd.Series | np.ndarray,
    exposures: pd.DataFrame,
    *,
    factor_cols: list[str] | None = None,
    weights: pd.Series | np.ndarray | None = None,
    return_clip: tuple[float, float] = (-0.2, 0.2),
) -> pd.Series:
    """
    Stage A: prod-aligned ``res_rtn = R_raw - B @ R_factor``.

    Delegates to ``residualize_returns`` (simultaneous GLS, sqrt-cap weights,
    ESTU estimation, industry-neutral constraint). ``factor_cols`` and
    ``weights`` are ignored when a full risk model frame is supplied.
    """
    from .residualize import residualize_returns

    if isinstance(y, pd.Series):
        series = y.reindex(exposures.index)
    else:
        series = pd.Series(np.asarray(y, dtype=float).reshape(-1), index=exposures.index)
    cap_col = 'capitalization' if 'capitalization' in exposures.columns else 'market_cap'
    if cap_col not in exposures.columns:
        exposures = exposures.copy()
        exposures['capitalization'] = 1.0
        cap_col = 'capitalization'
    return residualize_returns(series, exposures, return_clip=return_clip, cap_col=cap_col)


def ols_statsmodels(
    y: pd.Series,
    exposures: pd.DataFrame,
    *,
    factor_cols: list[str] | None = None,
    weights: pd.Series | None = None,
):
    """
    Stage A (optional): return a fitted ``statsmodels.api.WLS`` model.

    Requires ``statsmodels`` installed.
    """
    import statsmodels.api as sm

    cols = factor_cols or exposure_columns(exposures)
    X = exposures[cols].fillna(0.0)
    X = sm.add_constant(X)
    if weights is not None:
        return sm.WLS(y, X, weights=weights).fit()
    return sm.OLS(y, X).fit()


def optimizer_constraint_matrix(
    exposures: pd.DataFrame,
    symbols: list[str] | None = None,
    *,
    factor_cols: list[str] | None = None,
    symbol_col: str = 'symbol',
) -> tuple[np.ndarray, list[str], list[str]]:
    """
    Stage B: factor exposure matrix ``B`` where ``B[k, i]`` is stock *i* loading on factor *k*.

    Portfolio factor exposure: ``B @ w`` (``w`` aligned to ``symbols`` order).
    Linear constraint form: ``B @ w <= u`` and ``-B @ w <= -l``.
    """
    cols = factor_cols or exposure_columns(exposures)
    sub = exposures.copy()
    if symbols is not None:
        sub = sub.set_index(symbol_col).reindex(symbols)
    else:
        symbols = sub[symbol_col].tolist()
        sub = sub.set_index(symbol_col)
    B = sub[cols].fillna(0.0).values.T
    factor_names = [c.replace('lb_', '') for c in cols]
    return B, factor_names, list(symbols)


def optimizer_constraint_specs(
    exposures: pd.DataFrame,
    factor_limits: dict[str, tuple[float, float]],
    symbols: list[str] | None = None,
    *,
    factor_cols: list[str] | None = None,
    symbol_col: str = 'symbol',
) -> list[dict]:
    """
    Stage B: scipy / PyPortfolioOpt-ready constraint descriptors.

    Each item: ``{'type': 'ineq', 'fun': lambda w: bound - factor_exposure(w)}``.

    Example::

        limits = {'size': (-0.3, 0.3), 'volatility': (-0.5, 0.2)}
        specs = optimizer_constraint_specs(exposures, limits, symbols)
    """
    B, factor_names, syms = optimizer_constraint_matrix(
        exposures, symbols, factor_cols=factor_cols, symbol_col=symbol_col,
    )

    specs: list[dict] = []
    for k, name in enumerate(factor_names):
        if name not in factor_limits:
            continue
        lo, hi = factor_limits[name]
        b_row = B[k]

        def upper_fun(w, row=b_row, upper=hi):
            return upper - float(row @ w)

        def lower_fun(w, row=b_row, lower=lo):
            return float(row @ w) - lower

        specs.append({'type': 'ineq', 'fun': upper_fun, 'factor': name, 'side': 'upper'})
        specs.append({'type': 'ineq', 'fun': lower_fun, 'factor': name, 'side': 'lower'})
    return specs
