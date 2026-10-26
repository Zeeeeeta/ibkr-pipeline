#!/usr/bin/env python3
"""
Barra US TMT descriptor formulas (Mar 2015 Descriptor Details PDF).

Computes raw descriptor values per symbol from a long daily panel before
cross-sectional MAD / z-score in ``cross_section.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Descriptor windows (trading days) from MSCI Descriptor Details.
RSTR_T = 504
RSTR_LAG = 20
RSTR_HALFLIFE = 126

LTRSTR_T = 1008
LTRSTR_LAG = 273
LTRSTR_HALFLIFE = 504

STREV_DAYS = 21
STREV_HALFLIFE = 5

HBETA_DAYS = 252
HBETA_HALFLIFE = 63

RF_DEFAULT = 0.0


def exp_weights(n: int, half_life: float) -> np.ndarray:
    """Exponential weights for tau=1..n (tau=1 is oldest in the sum)."""
    if n <= 0:
        return np.array([])
    decay = 0.5 ** (1.0 / half_life)
    powers = np.arange(n - 1, -1, -1, dtype=float)
    w = decay ** powers
    return w / w.sum()


def weighted_least_squares_slope(
    y: np.ndarray,
    x: np.ndarray,
    half_life: float,
) -> float:
    """WLS slope of y on x with exponential weights (recent = higher weight)."""
    mask = np.isfinite(y) & np.isfinite(x)
    if mask.sum() < 10:
        return np.nan
    y = y[mask]
    x = x[mask]
    w = exp_weights(len(y), half_life)
    x_m = np.average(x, weights=w)
    y_m = np.average(y, weights=w)
    cov = np.average((x - x_m) * (y - y_m), weights=w)
    var = np.average((x - x_m) ** 2, weights=w)
    if var <= 0:
        return np.nan
    return float(cov / var)


def descriptor_lncap(market_cap: pd.Series) -> pd.Series:
    return np.log(market_cap.astype(float).clip(lower=1.0))


def descriptor_btop(
    market_cap: pd.Series,
    book_value_per_share: pd.Series | None,
    price: pd.Series,
) -> pd.Series:
    """Book-to-price (BTOP)."""
    if book_value_per_share is None:
        return pd.Series(np.nan, index=market_cap.index)
    book = book_value_per_share.astype(float)
    cap = market_cap.astype(float).replace(0, np.nan)
    return book * price.astype(float) / cap


def _excess_log_return_sum(
    stock_ret: np.ndarray,
    mkt_ret: np.ndarray,
    *,
    n_obs: int,
    lag: int,
    half_life: float,
) -> float:
    """Sum of weighted [ln(1+r) - ln(1+rm)] over trailing window with lag."""
    n = len(stock_ret)
    T = min(n_obs, n - lag - 1)
    if T < 20:
        return np.nan
    w = exp_weights(T, half_life)
    total = 0.0
    used = 0
    for tau in range(1, T + 1):
        idx = n - lag - tau
        if idx < 0:
            break
        rs = stock_ret[idx]
        rm = mkt_ret[idx] if idx < len(mkt_ret) else np.nan
        if not np.isfinite(rs) or not np.isfinite(rm):
            continue
        total += w[tau - 1] * (np.log1p(rs) - np.log1p(rm))
        used += 1
    return total if used >= max(10, T // 4) else np.nan


def descriptor_rstr(
    close: pd.Series,
    mkt_ret: pd.Series,
) -> pd.Series:
    """Relative strength (momentum), T=504, lag=20, half-life=126."""
    px = close.astype(float)
    rets = px.pct_change().values
    mkt = mkt_ret.reindex(close.index).fillna(RF_DEFAULT).values
    out = np.full(len(px), np.nan)
    for i in range(len(px)):
        sl = slice(0, i + 1)
        out[i] = _excess_log_return_sum(
            rets[sl], mkt[sl],
            n_obs=RSTR_T, lag=RSTR_LAG, half_life=RSTR_HALFLIFE,
        )
    return pd.Series(out, index=close.index)


def descriptor_strev(
    close: pd.Series,
    mkt_ret: pd.Series,
) -> pd.Series:
    """Short-term reversal: ~1 month excess log returns, half-life 5."""
    px = close.astype(float)
    rets = px.pct_change().values
    mkt = mkt_ret.reindex(close.index).fillna(RF_DEFAULT).values
    out = np.full(len(px), np.nan)
    for i in range(len(px)):
        start = max(0, i - STREV_DAYS + 1)
        seg_r = rets[start:i + 1]
        seg_m = mkt[start:i + 1]
        if len(seg_r) < 5:
            continue
        w = exp_weights(len(seg_r), STREV_HALFLIFE)
        excess = np.log1p(seg_r) - np.log1p(seg_m)
        mask = np.isfinite(excess)
        if mask.sum() < 3:
            continue
        out[i] = float(np.average(excess[mask], weights=w[mask]))
    return pd.Series(out, index=close.index)


def descriptor_ltrstr(
    close: pd.Series,
    mkt_ret: pd.Series,
) -> pd.Series:
    """Long-term reversal (LTRSTR); sign flipped when used as factor per Barra note."""
    px = close.astype(float)
    rets = px.pct_change().values
    mkt = mkt_ret.reindex(close.index).fillna(RF_DEFAULT).values
    out = np.full(len(px), np.nan)
    for i in range(len(px)):
        sl = slice(0, i + 1)
        val = _excess_log_return_sum(
            rets[sl], mkt[sl],
            n_obs=LTRSTR_T, lag=LTRSTR_LAG, half_life=LTRSTR_HALFLIFE,
        )
        out[i] = -val if np.isfinite(val) else np.nan
    return pd.Series(out, index=close.index)


def descriptor_str1(
    close: pd.Series,
    mkt_ret: pd.Series,
) -> pd.Series:
    """1-day reversal: ln(1+r) - ln(1+rf) on the same day."""
    rets = close.astype(float).pct_change()
    mkt = mkt_ret.reindex(close.index).fillna(RF_DEFAULT)
    return np.log1p(rets) - np.log1p(mkt)


def descriptor_hbeta(
    close: pd.Series,
    mkt_ret: pd.Series,
) -> pd.Series:
    """Historical beta: WLS slope vs cap-weighted market, 252d, half-life 63."""
    rets = close.astype(float).pct_change().values
    mkt = mkt_ret.reindex(close.index).fillna(RF_DEFAULT).values
    out = np.full(len(close), np.nan)
    for i in range(len(close)):
        start = max(0, i - HBETA_DAYS + 1)
        out[i] = weighted_least_squares_slope(
            rets[start:i + 1],
            mkt[start:i + 1],
            HBETA_HALFLIFE,
        )
    return pd.Series(out, index=close.index)


def descriptor_hsigma(
    close: pd.Series,
    mkt_ret: pd.Series,
) -> pd.Series:
    """Residual volatility proxy: std of CAPM residuals (252d)."""
    rets = close.astype(float).pct_change()
    mkt = mkt_ret.reindex(close.index).fillna(RF_DEFAULT)
    beta = descriptor_hbeta(close, mkt_ret)
    resid = rets - beta * mkt
    n = len(resid)
    if n < 10:
        return pd.Series(np.nan, index=close.index)
    eff = min(HBETA_DAYS, n)
    min_p = min(max(5, eff // 2), eff)
    return resid.rolling(eff, min_periods=min_p).std(ddof=0)


def _monthly_stom(panel: pd.DataFrame, date_col: str, vol_col: str, cap_col: str, price_col: str) -> pd.Series:
    """STOM = ln(monthly_volume / shares); shares = market_cap / price."""
    g = panel.copy()
    g['_dt'] = pd.to_datetime(g[date_col].astype(str), format='%Y%m%d', errors='coerce')
    g['_ym'] = g['_dt'].dt.to_period('M')
    shares = g[cap_col].astype(float) / g[price_col].astype(float).replace(0, np.nan)
    g['_shares'] = shares.clip(lower=1.0)
    monthly = g.groupby('_ym', group_keys=False).agg(
        vol=(vol_col, 'sum'),
        shares=('_shares', 'last'),
    )
    monthly['stom'] = np.log((monthly['vol'] / monthly['shares']).clip(lower=1e-12))
    g['_stom'] = g['_ym'].map(monthly['stom'])
    return g['_stom']


def descriptor_stom(
    panel: pd.DataFrame,
    *,
    date_col: str = 'date',
    volume_col: str = 'volume',
    market_cap_col: str = 'market_cap',
    price_col: str = 'close',
) -> pd.Series:
    return _monthly_stom(panel, date_col, volume_col, market_cap_col, price_col)


def cap_weighted_market_returns(
    panel: pd.DataFrame,
    date_col: str,
    *,
    price_col: str = 'close',
    cap_col: str = 'market_cap',
    symbol_col: str = 'symbol',
    estu_col: str | None = 'estu',
) -> pd.Series:
    """Daily cap-weighted market return; uses ESTU names when ``estu_col`` is set."""
    g = panel.sort_values([symbol_col, date_col]).copy()
    if estu_col and estu_col in g.columns:
        g = g[g[estu_col].astype(int) == 1]
    g['_ret'] = g.groupby(symbol_col, group_keys=False)[price_col].transform(
        lambda s: s.astype(float).pct_change()
    )
    cap = g[cap_col].fillna(0).clip(lower=0)
    g['_wc'] = cap
    g['_wr'] = g['_ret'] * g['_wc']

    def _mkt(day_df: pd.DataFrame) -> float:
        w = day_df['_wc'].sum()
        if w <= 0:
            return float(day_df['_ret'].mean())
        return float(day_df['_wr'].sum() / w)

    return g.groupby(date_col, group_keys=False).apply(_mkt, include_groups=False)


def compute_symbol_descriptors(
    panel: pd.DataFrame,
    mkt_ret: pd.Series,
    *,
    symbol_col: str = 'symbol',
    date_col: str = 'date',
    price_col: str = 'close',
    volume_col: str = 'volume',
    market_cap_col: str = 'market_cap',
    book_col: str = 'book_value_per_share',
    eps_col: str = 'eps_ttm',
) -> pd.DataFrame:
    """Attach Barra-style raw descriptor columns to a multi-symbol daily panel."""
    out = panel.copy()
    book = out[book_col] if book_col in out.columns else None
    eps = out[eps_col] if eps_col in out.columns else None

    pieces: list[pd.DataFrame] = []
    for sym, g in out.groupby(symbol_col, sort=False):
        g = g.sort_values(date_col)
        mkt = mkt_ret.reindex(g[date_col].values)
        mkt.index = g.index

        g = g.copy()
        g['raw_size'] = descriptor_lncap(g[market_cap_col])
        g['raw_value'] = descriptor_btop(g[market_cap_col], book, g[price_col])
        if eps is not None:
            g['raw_earnyild'] = eps.reindex(g.index).astype(float) / g[price_col].astype(float).replace(0, np.nan)
        g['raw_momentum'] = descriptor_rstr(g[price_col], mkt)
        g['raw_strevrsl'] = descriptor_strev(g[price_col], mkt)
        g['raw_ltrevrsl'] = descriptor_ltrstr(g[price_col], mkt)
        g['raw_onerevrsl'] = descriptor_str1(g[price_col], mkt)
        g['raw_beta'] = descriptor_hbeta(g[price_col], mkt)
        g['raw_volatility'] = descriptor_hsigma(g[price_col], mkt)
        g['raw_liquidity'] = _monthly_stom(g, date_col, volume_col, market_cap_col, price_col)
        pieces.append(g)

    return pd.concat(pieces, ignore_index=True)
