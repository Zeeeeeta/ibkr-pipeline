#!/usr/bin/env python3
"""Shared helpers for lit-exchange Reg SHO short-volume fetchers."""

from __future__ import annotations

import io
import os
import zipfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from ftplib import FTP, error_perm
from io import StringIO

import pandas as pd

from .paths import short_sale_path

USER_AGENT = 'ibkr-exss-fetch/1.0'
NYXDATA_HOST = 'ftp.nyxdata.com'
NYXDATA_ROOT = '/ShortData'
NASDAQ_HOST = 'ftp.nasdaqtrader.com'
CBOE_HOST = 'ftp.cboe.com'
CBOE_DEPRECATION_MARK = 'no longer be available for public download'

# Free EOD shvol zip windows on ftp.cboe.com (post-end dates serve deprecation stubs).
CBOE_VENUE_SPECS: dict[str, dict[str, str]] = {
    'bats': {
        'directory': 'bzx-equities/short-sale',
        'filename': 'BATSshvol{date}.txt.zip',
        'free_start': '20210104',
        'free_end': '20230601',
    },
    'baty': {
        'directory': 'byx-equities/short-sale',
        'filename': 'BYXXshvol{date}.txt.zip',
        'free_start': '20210104',
        'free_end': '20230601',
    },
    'edga': {
        'directory': 'edga-equities/short-sale',
        'filename': 'EDGAshvol{date}.txt.zip',
        'free_start': '20170501',
        'free_end': '20230601',
    },
    'edgx': {
        'directory': 'edgx-equities/short-sale',
        'filename': 'EDGXshvol{date}.txt.zip',
        'free_start': '20210104',
        'free_end': '20230601',
    },
}


def fetch_url(url: str, *, timeout: int = 60) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def fetch_ftp_file(host: str, path: str, *, timeout: int = 60) -> bytes | None:
    """Download one FTP path (leading slash, no scheme)."""
    parts = [p for p in path.split('/') if p]
    if not parts:
        return None
    filename = parts[-1]
    directory = '/' + '/'.join(parts[:-1])
    try:
        ftp = FTP(host, timeout=timeout)
        ftp.login()
        ftp.cwd(directory)
        chunks: list[bytes] = []

        def _collector(data: bytes) -> None:
            chunks.append(data)

        ftp.retrbinary(f'RETR {filename}', _collector)
        ftp.quit()
        return b''.join(chunks) if chunks else None
    except (OSError, TimeoutError, error_perm):
        return None


def nyxdata_txt_candidates(prefix: str, yyyymmdd: str) -> list[str]:
    """Candidate NYSE-group FTP paths for one daily pipe file."""
    year = yyyymmdd[:4]
    yyyymm = yyyymmdd[:6]
    base = f'{NYXDATA_ROOT}/{prefix}'
    return [
        f'{base}/current/{prefix}{yyyymmdd}.txt',
        f'{base}/{prefix}{year}/{prefix}{yyyymm}/{prefix}{yyyymmdd}.txt',
    ]


def fetch_nyxdata_txt(prefix: str, yyyymmdd: str) -> bytes | None:
    for path in nyxdata_txt_candidates(prefix, yyyymmdd):
        data = fetch_ftp_file(NYXDATA_HOST, path)
        if data:
            return data
    return None


def fetch_ftp_named(host: str, directory: str, filename: str, *, timeout: int = 60) -> bytes | None:
    return fetch_ftp_file(host, f'{directory.rstrip("/")}/{filename}', timeout=timeout)


def fetch_nasdaq_lit_txt(venue: str, yyyymmdd: str) -> bytes | None:
    """NASDAQ lit daily summary from ftp.nasdaqtrader.com/Files/shortsaledata/daily/."""
    specs = {
        'nasdaq': ('Files/shortsaledata/daily/nasdaq', f'NSDQshvol{yyyymmdd}.txt'),
        'nasdaq_bx': ('Files/shortsaledata/daily/bx', f'NQBXshvol{yyyymmdd}.txt'),
    }
    if venue not in specs:
        return None
    directory, filename = specs[venue]
    return fetch_ftp_named(NASDAQ_HOST, directory, filename)


def cboe_shvol_in_free_window(venue: str, yyyymmdd: str) -> bool:
    spec = CBOE_VENUE_SPECS.get(venue)
    if not spec:
        return False
    return spec['free_start'] <= yyyymmdd <= spec['free_end']


def fetch_cboe_shvol_zip(venue: str, yyyymmdd: str) -> bytes | None:
    """Cboe lit daily summary zip from ftp.cboe.com (free through ~2023-06-01)."""
    spec = CBOE_VENUE_SPECS.get(venue)
    if not spec or not cboe_shvol_in_free_window(venue, yyyymmdd):
        return None
    filename = spec['filename'].format(date=yyyymmdd)
    return fetch_ftp_named(CBOE_HOST, spec['directory'], filename)


def unzip_first_text(data: bytes) -> str | None:
    if not data:
        return None
    if data[:2] == b'PK':
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            name = zf.namelist()[0]
            return zf.read(name).decode('utf-8', errors='replace')
        except (zipfile.BadZipFile, IndexError, OSError):
            return None
    return data.decode('utf-8', errors='replace')


def is_cboe_deprecation_notice(text: str) -> bool:
    return CBOE_DEPRECATION_MARK in text


def _normalize_regsho_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [
        str(c).strip().lower().replace(' ', '_').replace('-', '_')
        for c in out.columns
    ]
    renames: dict[str, str] = {}
    for c in out.columns:
        if c in ('shortvolume', 'short_vol', 'short_volume'):
            renames[c] = 'shortvolume'
        elif c in ('totalvolume', 'total_vol', 'total_volume'):
            renames[c] = 'totalvolume'
        elif c in ('shortexemptvolume', 'short_exempt_volume'):
            renames[c] = 'shortexemptvolume'
        elif c in ('symbol', 'ticker'):
            renames[c] = 'symbol'
        elif c in ('market', 'ct_market', 'cta_market'):
            renames[c] = 'market'
    return out.rename(columns=renames)


def parse_regsho_pipe(text: str) -> pd.DataFrame:
    """Parse pipe-delimited Reg SHO daily short volume (NYSE/NASDAQ/Cboe variants)."""
    if is_cboe_deprecation_notice(text):
        return pd.DataFrame()
    lines = [
        ln for ln in text.strip().splitlines()
        if ln and not ln.upper().startswith('DATE|')
    ]
    if not lines:
        return pd.DataFrame()
    if lines[-1].split('|')[0].isdigit() and lines[-1].count('|') <= 1:
        lines = lines[:-1]
    if not lines:
        return pd.DataFrame()
    try:
        df = pd.read_csv(StringIO('\n'.join(lines)), sep='|', header=None)
        if df.shape[1] >= 5:
            df.columns = [f'col{i}' for i in range(df.shape[1])]
            # Date|Symbol|ShortVolume|TotalVolume|Market  (older)
            # Date|Symbol|Short Exempt|Short Volume|Total Volume|Market (newer)
            if df.shape[1] == 5:
                df.columns = ['date', 'symbol', 'shortvolume', 'totalvolume', 'market']
            elif df.shape[1] == 6:
                df.columns = [
                    'date', 'symbol', 'shortexemptvolume', 'shortvolume',
                    'totalvolume', 'market',
                ]
            else:
                df = pd.read_csv(StringIO('\n'.join(lines)), sep='|')
                df = _normalize_regsho_columns(df)
        else:
            df = pd.read_csv(StringIO('\n'.join(lines)), sep='|')
            df = _normalize_regsho_columns(df)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

    df = _normalize_regsho_columns(df)
    if 'symbol' in df.columns:
        df['symbol'] = df['symbol'].astype(str).str.strip().str.upper()
    for col in ('shortvolume', 'totalvolume', 'shortexemptvolume'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'market' in df.columns:
        df['market'] = df['market'].astype(str).str.strip().str.upper()
    return df


def split_by_market(
    df: pd.DataFrame,
    market_to_venue: dict[str, str],
) -> dict[str, pd.DataFrame]:
    if df.empty or 'market' not in df.columns:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for market, venue in market_to_venue.items():
        part = df[df['market'] == market.upper()]
        if not part.empty:
            out[venue] = part
    return out


def aggregate_symbol_volumes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=['symbol', 'shortvolume', 'totalvolume'])
    cols = ['symbol', 'shortvolume', 'totalvolume']
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f'Missing columns for write: {missing}')
    out = df.groupby('symbol', as_index=False).agg(
        shortvolume=('shortvolume', 'sum'),
        totalvolume=('totalvolume', 'sum'),
    )
    return out


def write_venue_day(
    yyyymmdd: str,
    venue: str,
    df: pd.DataFrame,
    *,
    dry_run: bool = False,
) -> int:
    out = aggregate_symbol_volumes(df)
    if out.empty:
        return 0
    path = short_sale_path(yyyymmdd, venue)
    if dry_run:
        print(f'  would write {path} rows={len(out)}')
        return len(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, compression='gzip')
    return len(out)


def env_url_templates(var_name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(var_name, '').strip()
    if raw:
        return tuple(u.strip() for u in raw.split(',') if u.strip())
    return defaults


def load_trading_days_or_weekdays(start: str, end: str) -> list[str]:
    from ..opcl.calendar import load_trading_days

    days = load_trading_days(start, end, feature_fallback=False)
    if days:
        return days
    dt = datetime.strptime(start, '%Y%m%d')
    end_dt = datetime.strptime(end, '%Y%m%d')
    out: list[str] = []
    while dt <= end_dt:
        if dt.weekday() < 5:
            out.append(dt.strftime('%Y%m%d'))
        dt += timedelta(days=1)
    return out
