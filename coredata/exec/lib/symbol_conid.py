#!/usr/bin/env python3
"""Cache underlying conId for reqSecDefOptParams."""

import csv
from pathlib import Path

from ib_async import IB, Stock

from .paths import DEFAULT_REF_DIR

# Well-known conIds (US equities)
_BUILTIN = {
    'AAPL': 265598,
    'MSFT': 272093,
    'GOOGL': 208813720,
    'AMZN': 3691937,
    'META': 107113386,
}


class SymbolConIdRegistry:
    def __init__(self, path: Path = None):
        self.path = path or (DEFAULT_REF_DIR / 'symbol_conid.csv')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._map = dict(_BUILTIN)
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with self.path.open(newline='') as f:
            for row in csv.DictReader(f):
                self._map[row['symbol'].upper()] = int(row['con_id'])

    def _save(self, symbol: str, con_id: int):
        rows = sorted(self._map.items())
        with self.path.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['symbol', 'con_id'])
            for sym, cid in rows:
                w.writerow([sym, cid])

    def con_id_for(self, ib: IB, symbol: str) -> int:
        sym = symbol.upper()
        if sym in self._map:
            return self._map[sym]
        # matchingSymbols is faster than qualifyContracts for many setups
        try:
            for m in ib.reqMatchingSymbols(sym):
                c = m.contract
                if c.secType == 'STK' and c.symbol.upper() == sym:
                    self._map[sym] = c.conId
                    self._save(sym, c.conId)
                    return c.conId
        except Exception:
            pass
        try:
            q = ib.qualifyContracts(Stock(sym, 'SMART', 'USD'))
            if q:
                self._map[sym] = q[0].conId
                self._save(sym, q[0].conId)
                return q[0].conId
        except Exception:
            pass
        return 0
