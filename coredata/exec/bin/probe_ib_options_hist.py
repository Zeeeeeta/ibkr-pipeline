#!/usr/bin/env python3
"""Probe IB historical options data modes (requires TWS)."""

import argparse
import json
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from ib_async import IB, Option, Stock, util

from lib.ib_connect import connect_ib
from lib.paths import PROBE_RESULTS


def probe(symbol='AAPL', client_id=90):
    ib = connect_ib(client_id=client_id, log_errors=True, request_timeout=180)
    results = {'symbol': symbol, 'hist': {}, 'generic_ticks': {}}
    try:
        from lib.symbol_conid import SymbolConIdRegistry
        cid = SymbolConIdRegistry().con_id_for(ib, symbol) or 265598
        chains = ib.reqSecDefOptParams(symbol, '', 'STK', cid)
        chain = next(c for c in chains if c.exchange == 'SMART')
        expiry = sorted(chain.expirations)[-1]
        strikes = sorted(chain.strikes)
        mid = strikes[len(strikes) // 2]
        opt = Option(symbol, expiry, mid, 'C', 'SMART')
        opt.tradingClass = chain.tradingClass
        opt.multiplier = chain.multiplier
        qualified = ib.qualifyContracts(opt)
        if not qualified:
            results['qualify'] = {'ok': False}
            return results
        opt = qualified[0]
        results['qualify'] = {'ok': True, 'conId': opt.conId, 'localSymbol': opt.localSymbol}

        for mode in ('TRADES', 'MIDPOINT', 'BID_ASK'):
            for bar_size, duration in (('1 day', '5 D'), ('1 hour', '10 D')):
                key = f'{mode}_{bar_size.replace(" ", "_")}'
                try:
                    bars = ib.reqHistoricalData(
                        opt, endDateTime='', durationStr=duration,
                        barSizeSetting=bar_size, whatToShow=mode,
                        useRTH=True, formatDate=1,
                    )
                    n = len(bars) if bars else 0
                    vol = 0
                    if bars:
                        df = util.df(bars)
                        vol = int(df['volume'].fillna(0).sum()) if 'volume' in df.columns else 0
                    results['hist'][key] = {'bars': n, 'total_volume': vol, 'ok': n > 0}
                except Exception as e:
                    results['hist'][key] = {'ok': False, 'error': str(e)}
                ib.sleep(0.2)

        for tick_list, label in (('100', 'volume_100'), ('101', 'oi_101')):
            try:
                t = ib.reqMktData(opt, genericTickList=tick_list, snapshot=True)
                ib.sleep(1.0)
                attrs = {k: v for k, v in t.__dict__.items() if not k.startswith('_') and v not in (None, 0, '')}
                results['generic_ticks'][label] = attrs
                ib.cancelMktData(opt)
            except Exception as e:
                results['generic_ticks'][label] = {'error': str(e)}
    finally:
        ib.disconnect()

    PROBE_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    PROBE_RESULTS.write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2))
    print(f'Wrote {PROBE_RESULTS}')
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', default='AAPL')
    p.add_argument('--client-id', type=int, default=90)
    args = p.parse_args()
    probe(args.symbol, args.client_id)
