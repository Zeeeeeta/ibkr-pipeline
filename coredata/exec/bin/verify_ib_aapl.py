#!/usr/bin/env python3
"""Verify IB returns non-zero option history bars for AAPL (TWS required)."""

import sys
from datetime import datetime
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from ib_async import Option, util

from lib.contract_builder import hist_bars_to_daily, qualify_option
from lib.ib_connect import connect_ib


def main():
    ib = connect_ib(client_id=50, log_errors=True, request_timeout=180)
    try:
        today = datetime.now().strftime('%Y%m%d')
        chains = ib.reqSecDefOptParams('AAPL', '', 'STK', 265598)
        chain = next(c for c in chains if c.exchange == 'SMART')
        expirations = sorted(e for e in chain.expirations if e >= today)
        ref = 275.0
        opt = None
        for exp in expirations:
            strike = min(chain.strikes, key=lambda s: abs(s - ref))
            candidate = Option('AAPL', exp, strike, 'C', 'SMART')
            candidate.tradingClass = chain.tradingClass
            candidate.multiplier = chain.multiplier
            opt = qualify_option(ib, candidate, sleep_ms=50)
            if opt is not None:
                print(f'Contract: {exp} {strike}C conId={opt.conId} local={opt.localSymbol}')
                break
        if opt is None:
            print('FAIL: could not qualify any AAPL option')
            return 1

        daily, mode = hist_bars_to_daily(ib, opt, '', sleep_ms=100)
        if daily.empty:
            print('FAIL: no bars from hist_bars_to_daily')
            return 1
        vol = int(daily['volume'].fillna(0).sum())
        print(f'OK: mode={mode} days={len(daily)} total_volume={vol}')
        print(daily.tail(3).to_string(index=False))
        return 0
    finally:
        ib.disconnect()


if __name__ == '__main__':
    sys.exit(main() or 0)
