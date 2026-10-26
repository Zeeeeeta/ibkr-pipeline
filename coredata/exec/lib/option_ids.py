#!/usr/bin/env python3
"""Persistent symbol -> sid registry; optsid = IB conId."""

import csv
from pathlib import Path

from .paths import DEFAULT_REF_DIR


class SymbolSidRegistry:
    def __init__(self, path=None):
        self.path = path or (DEFAULT_REF_DIR / 'symbol_sid.csv')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._symbol_to_sid: dict[str, int] = {}
        self._next_sid = 1
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with self.path.open(newline='') as f:
            for row in csv.DictReader(f):
                sym = row['symbol'].strip().upper()
                sid = int(row['sid'])
                self._symbol_to_sid[sym] = sid
                self._next_sid = max(self._next_sid, sid + 1)

    def sid_for(self, symbol: str) -> int:
        sym = symbol.strip().upper()
        if sym not in self._symbol_to_sid:
            self._symbol_to_sid[sym] = self._next_sid
            self._next_sid += 1
            self._flush()
        return self._symbol_to_sid[sym]

    def _flush(self):
        with self.path.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['symbol', 'sid'])
            for sym in sorted(self._symbol_to_sid):
                w.writerow([sym, self._symbol_to_sid[sym]])


def contract_key(symbol: str, expiry: str, strike: float, right: str) -> str:
    return f'{symbol.upper()}|{expiry}|{strike}|{right}'
