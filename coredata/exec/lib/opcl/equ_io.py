#!/usr/bin/env python3
import pandas as pd

from .paths import equ_prices_path


def load_equ_day(yyyymmdd: str) -> pd.DataFrame:
    p = equ_prices_path(yyyymmdd)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    df['date'] = yyyymmdd
    if 'symbol' in df.columns:
        df['underlying_symbol'] = df['symbol']
    if 'underlying_symbol' in df.columns:
        df = df.drop_duplicates('underlying_symbol', keep='last')
    return df


def prev_close_map(yyyymmdd: str) -> pd.Series:
    """Load T-1 closes keyed by symbol (requires calendar walk — single prev file)."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(yyyymmdd, '%Y%m%d') - timedelta(days=1)
    # walk back up to 5 calendar days
    for _ in range(5):
        prev = dt.strftime('%Y%m%d')
        df = load_equ_day(prev)
        if not df.empty:
            s = df.drop_duplicates('underlying_symbol').set_index('underlying_symbol')['close']
            return s
        dt -= timedelta(days=1)
    return pd.Series(dtype=float)


def adv_21d(symbol: str, end_yyyymmdd: str) -> float:
    """Rough ADV from available equ files (up to 21 files back)."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(end_yyyymmdd, '%Y%m%d')
    vols = []
    for _ in range(30):
        if len(vols) >= 21:
            break
        ymd = dt.strftime('%Y%m%d')
        df = load_equ_day(ymd)
        if not df.empty and symbol in df['underlying_symbol'].values:
            v = df.loc[df['underlying_symbol'] == symbol, 'volume']
            if len(v):
                vols.append(float(v.iloc[0]))
        dt -= timedelta(days=1)
    return float(sum(vols) / len(vols)) if vols else 0.0
