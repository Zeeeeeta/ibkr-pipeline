#!/usr/bin/env python3
"""Build and fetch option contract EOD rows from IB."""

from datetime import datetime

import pandas as pd
from ib_async import IB, Option, Stock, util

from .cboe_schema import FLOW_COLUMNS
from .ib_options_writer import empty_row_template
from .option_ids import SymbolSidRegistry, contract_key
from .symbol_conid import SymbolConIdRegistry


def parse_market_cap(val):
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


def load_universe(universe_path, min_cap=10e9):
    univ_df = pd.read_csv(universe_path)
    univ_df['parsed_cap'] = univ_df['Market Cap'].apply(parse_market_cap)
    filtered = univ_df[
        (univ_df['parsed_cap'] >= min_cap) & (univ_df['Symbol'].str.isalpha())
    ].copy()
    symbols = filtered['Symbol'].dropna().unique().tolist()
    return filtered, symbols


def ref_price_for_symbol(filtered_df, symbol: str):
    rows = filtered_df[filtered_df['Symbol'] == symbol]
    if rows.empty:
        return None
    raw = str(rows.iloc[0]['Last Sale']).replace('$', '').strip()
    try:
        return float(raw)
    except ValueError:
        return None


def pick_expirations(chain, as_of_yyyymmdd: str, max_expirations: int, anchor_yyyymmdd: str = None):
    """Pick expiries with 21–90 calendar DTE from anchor (for historical backfill)."""
    anchor = anchor_yyyymmdd or as_of_yyyymmdd
    dt_anchor = datetime.strptime(anchor, '%Y%m%d')
    candidates = []
    for exp in chain.expirations:
        dt_exp = datetime.strptime(exp, '%Y%m%d')
        dte = (dt_exp - dt_anchor).days
        if 21 <= dte <= 90:
            candidates.append((dte, exp))
    candidates.sort()
    if candidates:
        seen = []
        for _, exp in candidates:
            if exp not in seen:
                seen.append(exp)
            if len(seen) >= max_expirations:
                break
        return seen
    exps = sorted(exp for exp in chain.expirations if exp >= as_of_yyyymmdd)
    return exps[:max_expirations]


def ref_price_from_equ(symbol: str, yyyymmdd: str):
    from datetime import datetime, timedelta
    from .opcl.equ_io import load_equ_day
    sym = symbol.upper()
    dt = datetime.strptime(yyyymmdd, '%Y%m%d')
    for _ in range(10):
        equ = load_equ_day(dt.strftime('%Y%m%d'))
        if not equ.empty:
            row = equ.loc[equ['underlying_symbol'] == sym]
            if not row.empty:
                return float(row.iloc[0]['close'])
        dt -= timedelta(days=1)
    return None


def strikes_near_ref(chain, min_strike, max_strike, max_strikes: int, ref: float = None):
    in_band = sorted(s for s in chain.strikes if min_strike <= s <= max_strike)
    if not in_band and ref is not None:
        in_band = sorted(chain.strikes, key=lambda s: abs(s - ref))[:max_strikes]
    elif not in_band:
        mid = sorted(chain.strikes)[len(chain.strikes) // 2]
        in_band = sorted(chain.strikes, key=lambda s: abs(s - mid))[:max_strikes]
    elif len(in_band) > max_strikes:
        mid = ref if ref is not None else (min_strike + max_strike) / 2.0
        in_band = sorted(in_band, key=lambda s: abs(s - mid))[:max_strikes]
    return sorted(in_band)


def build_option_contracts(symbol, chain, expirations, min_strike, max_strike, max_strikes: int = 12, ref: float = None):
    in_band = strikes_near_ref(chain, min_strike, max_strike, max_strikes, ref)
    contracts = []
    for expiry in expirations:
        for strike in in_band:
            contracts.append(Option(symbol, expiry, strike, 'C', 'SMART'))
            contracts.append(Option(symbol, expiry, strike, 'P', 'SMART'))
    return contracts


def _days_to_expire(quote_yyyymmdd: str, expiry_yyyymmdd: str) -> int:
    q = datetime.strptime(quote_yyyymmdd, '%Y%m%d').date()
    e = datetime.strptime(expiry_yyyymmdd, '%Y%m%d').date()
    return max((e - q).days, 0)


def _format_expiry(expiry: str) -> str:
    if len(expiry) == 8:
        return f'{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}'
    return expiry


def _format_quote_date(yyyymmdd: str) -> str:
    return f'{yyyymmdd[4:6]}/{yyyymmdd[6:8]}/{yyyymmdd[:4]}'


def qualify_option(ib: IB, contract, sleep_ms: int = 100):
    """Resolve conId/localSymbol for one option (required for hist + market data)."""
    try:
        qualified = ib.qualifyContracts(contract)
        if qualified and qualified[0] is not None and getattr(qualified[0], 'conId', 0):
            ib.sleep(sleep_ms / 1000.0)
            return qualified[0]
    except Exception:
        pass
    try:
        details = ib.reqContractDetails(contract)
        if details:
            ib.sleep(sleep_ms / 1000.0)
            return details[0].contract
    except Exception:
        pass
    return None


def fetch_open_interest(ib: IB, contract, wait_sec: float = 0.5):
    try:
        t = ib.reqMktData(contract, snapshot=True, regulatorySnapshot=False)
        ib.sleep(wait_sec)
        oi = getattr(t, 'openInterest', None)
        if oi is None or (isinstance(oi, float) and oi != oi):
            oi = getattr(t, 'callOpenInterest', None)
        ib.cancelMktData(contract)
        if oi is not None and not (isinstance(oi, float) and oi != oi) and oi > 0:
            return int(oi)
    except Exception:
        pass
    return None


def hist_bars_to_daily(ib: IB, contract, what_to_show: str, sleep_ms: int, end_datetime: str = ''):
    """Try 1 hour and 1 day bars across TRADES/MIDPOINT/BID_ASK."""
    modes = [what_to_show] if what_to_show else ['TRADES', 'MIDPOINT', 'BID_ASK']
    if end_datetime:
        attempts = (('1 hour', '1 M', True), ('1 hour', '1 M', False))
    else:
        attempts = (
            ('1 hour', '1 M', True),
            ('1 hour', '1 M', False),
            ('1 hour', '10 D', True),
            ('1 hour', '10 D', False),
        )
    for mode in modes:
        for bar_size, duration, use_rth in attempts:
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime=end_datetime,
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow=mode,
                    useRTH=use_rth,
                    formatDate=1,
                )
                if not bars:
                    continue
                df = util.df(bars)
                df['date_str'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
                daily = df.groupby('date_str').agg(
                    open=('open', 'first'),
                    high=('high', 'max'),
                    low=('low', 'min'),
                    close=('close', 'last'),
                    volume=('volume', 'sum'),
                ).reset_index()
                if not daily.empty:
                    return daily, mode
            except Exception:
                continue
            ib.sleep(sleep_ms / 1000.0)
    return pd.DataFrame(), None


def daily_to_eod_rows(
    contract,
    daily_df: pd.DataFrame,
    registry: SymbolSidRegistry,
    open_interest,
    flow_source: str = 'UNAVAILABLE_IB',
):
    rows = []
    sym = contract.symbol
    sid = registry.sid_for(sym)
    expiry = contract.lastTradeDateOrContractMonth
    optsid = contract.conId or abs(hash(contract_key(sym, expiry, contract.strike, contract.right))) % (2**31 - 1)

    prev_close = None
    prev_oi = None
    sorted_days = daily_df.sort_values('date_str')

    for _, bar in sorted_days.iterrows():
        row = empty_row_template(flow_source=flow_source)
        ymd = bar['date_str']
        row.update({
            'sid': sid,
            'optsid': optsid,
            'con_id': optsid,
            'flow_source': flow_source,
            'quote_date': _format_quote_date(ymd),
            'underlying_symbol': sym,
            'security_type': 1,
            'option_symbol': sym,
            'expiration_date': _format_expiry(expiry),
            'strike_price': contract.strike,
            'call_put_flag': contract.right,
            'days_to_expire': _days_to_expire(ymd, expiry),
            'series_type': 'S',
            'first_trade_price': bar['open'],
            'high_trade_price': bar['high'],
            'low_trade_price': bar['low'],
            'last_trade_price': bar['close'],
            'total_exchange_vol': int(bar['volume']) if pd.notna(bar['volume']) else None,
            'open_interest': open_interest,
            'previous_close': prev_close,
            'previous_open_interest': prev_oi,
        })
        for col in FLOW_COLUMNS:
            row[col] = None
        prev_close = bar['close']
        prev_oi = open_interest
        rows.append(row)
    return rows


def process_symbol(
    ib: IB,
    symbol: str,
    filtered_df,
    registry: SymbolSidRegistry,
    conid_registry: SymbolConIdRegistry,
    as_of_yyyymmdd: str,
    max_expirations: int,
    strike_pct: float,
    what_to_show: str,
    sleep_ms: int,
    fetch_oi: bool,
    max_strikes: int = 12,
    end_datetime: str = '',
    anchor_yyyymmdd: str = '',
):
    stats = {'qualified': 0, 'rows': 0, 'skipped_hist': 0, 'skipped_qualify': 0}
    con_id = conid_registry.con_id_for(ib, symbol)
    if not con_id:
        return [], stats
    chains = ib.reqSecDefOptParams(symbol, '', 'STK', con_id)
    if not chains:
        return [], stats
    chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
    anchor = anchor_yyyymmdd or as_of_yyyymmdd
    expirations = pick_expirations(chain, as_of_yyyymmdd, max_expirations, anchor)
    if not expirations:
        return [], stats

    ref = ref_price_from_equ(symbol, anchor) or ref_price_for_symbol(filtered_df, symbol)
    if ref is None:
        min_strike, max_strike = 0.0, 99999.0
    else:
        min_strike = ref * (1.0 - strike_pct)
        max_strike = ref * (1.0 + strike_pct)

    sub = build_option_contracts(symbol, chain, expirations, min_strike, max_strike, max_strikes, ref=ref)
    if not sub:
        return [], stats

    for c in sub:
        c.tradingClass = chain.tradingClass
        c.multiplier = chain.multiplier
    qualified = sub

    stats['qualified'] = len(qualified)
    all_rows = []

    for idx, contract in enumerate(qualified, 1):
        qc = qualify_option(ib, contract, sleep_ms)
        if qc is None:
            stats['skipped_qualify'] += 1
            continue
        daily, _mode = hist_bars_to_daily(ib, qc, what_to_show, sleep_ms, end_datetime)
        if daily.empty:
            stats['skipped_hist'] += 1
            continue
        if anchor_yyyymmdd:
            daily = daily[daily['date_str'] <= anchor_yyyymmdd]
        if daily.empty:
            stats['skipped_hist'] += 1
            continue
        oi = fetch_open_interest(ib, qc) if fetch_oi else None
        all_rows.extend(
            daily_to_eod_rows(qc, daily, registry, oi)
        )
        stats['rows'] += len(daily)

    return all_rows, stats
