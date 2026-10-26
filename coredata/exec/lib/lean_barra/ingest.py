#!/usr/bin/env python3
"""Data ingestion: FMP API, Parquet/DuckDB, local equity price store."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ..paths import DEFAULT_REF_DIR, DEFAULT_UNIVERSE
from ..opcl.equ_io import load_equ_day
from ..opcl.paths import equ_prices_path
from .paths import FUNDAMENTALS_CACHE


def parse_market_cap(val) -> float:
    if pd.isna(val):
        return 0.0
    val_str = str(val).strip().upper().replace('$', '').replace(',', '')
    if not val_str:
        return 0.0
    try:
        if val_str.endswith('T'):
            return float(val_str[:-1]) * 1e12
        if val_str.endswith('B'):
            return float(val_str[:-1]) * 1e9
        if val_str.endswith('M'):
            return float(val_str[:-1]) * 1e6
        return float(val_str)
    except ValueError:
        return 0.0


def _parse_price(val) -> float:
    if pd.isna(val):
        return 0.0
    s = str(val).strip().replace('$', '').replace(',', '')
    try:
        return float(s)
    except ValueError:
        return 0.0


def load_universe_cap_shares(universe_path: Path | None = None) -> pd.DataFrame:
    """
    Static screener cap and implied shares (cap / last sale).

    Used to scale daily ``close * shares`` toward Barra last-day common equity cap.
    """
    p = universe_path or DEFAULT_UNIVERSE
    df = pd.read_csv(p)
    sym_col = 'Symbol' if 'Symbol' in df.columns else 'symbol'
    cap_col = 'Market Cap' if 'Market Cap' in df.columns else 'market_cap'
    price_col = 'Last Sale' if 'Last Sale' in df.columns else 'last_sale'
    rows = []
    for _, r in df.iterrows():
        sym = str(r[sym_col])
        cap = parse_market_cap(r.get(cap_col))
        px = _parse_price(r.get(price_col))
        shares = cap / px if cap > 0 and px > 0 else np.nan
        rows.append({'symbol': sym, 'screener_cap': cap, 'screener_price': px, 'shares_out': shares})
    return pd.DataFrame(rows)


def load_universe_symbols(universe_path: Path | None = None) -> list[str]:
    p = universe_path or DEFAULT_UNIVERSE
    df = pd.read_csv(p)
    sym_col = 'Symbol' if 'Symbol' in df.columns else 'symbol'
    return df[sym_col].dropna().astype(str).unique().tolist()


def load_symbol_sid(ref_dir: Path | None = None) -> pd.DataFrame:
    p = (ref_dir or DEFAULT_REF_DIR) / 'symbol_sid.csv'
    if not p.exists():
        return pd.DataFrame(columns=['symbol', 'sid'])
    return pd.read_csv(p)


def load_metrics_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names for the lean_barra pipeline."""
    out = df.copy()
    renames = {}
    if 'underlying_symbol' in out.columns and 'symbol' not in out.columns:
        renames['underlying_symbol'] = 'symbol'
    if 'quote_ymd' in out.columns and 'date' not in out.columns:
        renames['quote_ymd'] = 'date'
    if 'yyyymmdd' in out.columns and 'date' not in out.columns:
        renames['yyyymmdd'] = 'date'
    out = out.rename(columns=renames)
    if 'date' in out.columns:
        out['date'] = out['date'].astype(str).str.replace('-', '').str[:8]
    return out


def load_metrics_parquet(path: Path | str) -> pd.DataFrame:
    return load_metrics_dataframe(pd.read_parquet(path))


def load_metrics_duckdb(
    query: str,
    db_path: Path | str,
) -> pd.DataFrame:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return load_metrics_dataframe(con.execute(query).df())
    finally:
        con.close()


def _fmp_get(url: str, api_key: str) -> list | dict:
    sep = '&' if '?' in url else '?'
    full = f'{url}{sep}apikey={api_key}'
    req = Request(full, headers={'User-Agent': 'lean-barra/1.0'})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_fmp_key_metrics(
    symbols: list[str],
    api_key: str,
    *,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Pull book value and EPS from FMP ``/api/v3/key-metrics/{symbol}``."""
    rows = []
    for sym in symbols:
        try:
            data = _fmp_get(f'https://financialmodelingprep.com/api/v3/key-metrics/{sym}', api_key)
        except (URLError, TimeoutError, json.JSONDecodeError):
            continue
        if not data:
            continue
        rec = data[0] if isinstance(data, list) else data
        rows.append({
            'symbol': sym,
            'date': (as_of or str(rec.get('date', ''))).replace('-', '')[:8],
            'book_value_per_share': rec.get('bookValuePerShare'),
            'eps_ttm': rec.get('netIncomePerShare'),
            'market_cap': rec.get('marketCap'),
            'dividend_yield': rec.get('dividendYield'),
            'debt_to_equity': rec.get('debtToEquity'),
            'roe': rec.get('roe'),
            'eps_growth': rec.get('revenuePerShareGrowth') or rec.get('epsGrowth'),
        })
    return pd.DataFrame(rows)


def fetch_fmp_profiles(symbols: list[str], api_key: str) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        try:
            data = _fmp_get(f'https://financialmodelingprep.com/api/v3/profile/{sym}', api_key)
        except (URLError, TimeoutError, json.JSONDecodeError):
            continue
        if not data:
            continue
        rec = data[0] if isinstance(data, list) else data
        rows.append({
            'symbol': sym,
            'market_cap': rec.get('mktCap') or rec.get('marketCap'),
        })
    return pd.DataFrame(rows)


def load_or_fetch_fundamentals(
    symbols: list[str],
    *,
    api_key: str | None = None,
    as_of: str | None = None,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    cache = cache_path or FUNDAMENTALS_CACHE
    if cache.exists() and not api_key:
        cached = pd.read_parquet(cache)
        return cached[cached['symbol'].isin(symbols)]
    if not api_key:
        return pd.DataFrame(columns=[
            'symbol', 'book_value_per_share', 'eps_ttm', 'market_cap',
            'dividend_yield', 'debt_to_equity', 'roe', 'eps_growth',
        ])
    metrics = fetch_fmp_key_metrics(symbols, api_key, as_of=as_of)
    caps = fetch_fmp_profiles(symbols, api_key)
    if not caps.empty:
        metrics = metrics.merge(caps, on='symbol', how='left', suffixes=('', '_profile'))
        if 'market_cap_profile' in metrics.columns:
            metrics['market_cap'] = metrics['market_cap'].fillna(metrics['market_cap_profile'])
            metrics = metrics.drop(columns=['market_cap_profile'])
    if not metrics.empty:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            old = pd.read_parquet(cache)
            merged = pd.concat([old, metrics]).drop_duplicates('symbol', keep='last')
            merged.to_parquet(cache, index=False)
        else:
            metrics.to_parquet(cache, index=False)
    return metrics


def _list_equ_price_dates(year: str, price_root: Path) -> list[str]:
    year_dir = price_root / year
    if not year_dir.exists():
        return []
    return sorted(p.stem.split('.')[0] for p in year_dir.glob('*.equ_prices.csv'))


def build_metrics_from_equ_prices(
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    price_root: Path | None = None,
    universe_path: Path | None = None,
    fundamentals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build long-format daily metrics from local ``*.equ_prices.csv`` files.

    Market cap comes from universe screener when available; fundamentals merge
    optionally supplies book value / EPS for the value factor.
    """
    root = price_root or equ_prices_path(end_date).parent.parent
    sym_set = set(symbols)
    cap_shares = load_universe_cap_shares(universe_path) if universe_path and Path(universe_path).exists() else pd.DataFrame()

    years = sorted({start_date[:4], end_date[:4]})
    dates: list[str] = []
    for y in years:
        for d in _list_equ_price_dates(y, root):
            if start_date <= d <= end_date:
                dates.append(d)

    rows: list[dict] = []
    for ymd in dates:
        day = load_equ_day(ymd)
        if day.empty:
            continue
        sym_col = 'underlying_symbol' if 'underlying_symbol' in day.columns else 'symbol'
        sub = day[day[sym_col].isin(sym_set)]
        for _, r in sub.iterrows():
            sym = str(r[sym_col])
            close = float(r['close'])
            cap = np.nan
            if not cap_shares.empty and sym in cap_shares['symbol'].values:
                rec = cap_shares.loc[cap_shares['symbol'] == sym].iloc[0]
                sh = rec['shares_out']
                if pd.notna(sh) and sh > 0 and close > 0:
                    cap = close * float(sh)
                elif rec['screener_cap'] > 0:
                    cap = float(rec['screener_cap'])
            rows.append({
                'symbol': sym,
                'date': ymd,
                'close': close,
                'volume': float(r.get('volume', 0) or 0),
                'market_cap': cap,
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    if fundamentals is not None and not fundamentals.empty:
        fund = fundamentals.drop_duplicates('symbol', keep='last')
        out = out.merge(fund, on='symbol', how='left', suffixes=('', '_fund'))
        for col in (
            'book_value_per_share', 'eps_ttm', 'market_cap',
            'dividend_yield', 'debt_to_equity', 'roe', 'eps_growth',
        ):
            fund_col = f'{col}_fund'
            if fund_col in out.columns:
                out[col] = out[col].fillna(out[fund_col])
                out = out.drop(columns=[fund_col])

    return out.sort_values(['symbol', 'date']).reset_index(drop=True)
