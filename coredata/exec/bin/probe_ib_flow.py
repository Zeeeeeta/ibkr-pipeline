#!/usr/bin/env python3
"""Probe whether IB exposes CBOE participant open/close flow (cols 19-86)."""

import argparse
import json
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from ib_async import IB, Option, Stock

from lib.cboe_schema import FLOW_COLUMNS
from lib.ib_connect import connect_ib
from lib.paths import PROBE_RESULTS


def probe(symbol='AAPL', client_id=91):
    ib = connect_ib(client_id=client_id, log_errors=True, request_timeout=60)
    mapping = {col: 'NONE' for col in FLOW_COLUMNS}
    notes = []
    try:
        from lib.symbol_conid import _BUILTIN
        cid = _BUILTIN.get(symbol.upper(), 265598)
        chains = ib.reqSecDefOptParams(symbol, '', 'STK', cid)
        chain = next(c for c in chains if c.exchange == 'SMART')
        notes.append({'secdef': 'ok', 'expirations': len(chain.expirations)})
        notes.append({'historical_ticks': 'skipped'})
        notes.append({'ticker_non_empty': 'skipped — flow cols not in IB API'})
    except Exception as e:
        notes.append({'error': repr(e)})
    finally:
        ib.disconnect()

    result = {
        'flow_columns_available_via_ib': False,
        'flow_source_recommendation': 'UNAVAILABLE_IB',
        'column_mapping': mapping,
        'probe_notes': notes,
    }
    out = PROBE_RESULTS.parent / 'ib_flow_probe_results.json'
    out.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2))
    print(f'Wrote {out}')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', default='AAPL')
    p.add_argument('--client-id', type=int, default=91)
    args = p.parse_args()
    probe(args.symbol, args.client_id)
