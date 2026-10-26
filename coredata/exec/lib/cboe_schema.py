#!/usr/bin/env python3
"""CBOE Open/Close EOD v1.3 column definitions."""

from pathlib import Path

_SCHEMA_FILE = Path(__file__).resolve().parents[1] / 'schemas' / 'cboe_open_close_eod_v1.3_columns.txt'

INTERNAL_COLS = ('sid', 'optsid', 'flow_source', 'con_id')

FLOW_COL_START = 'firm_open_buy_qty'


def load_cboe_columns():
    cols = []
    for line in _SCHEMA_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        cols.append(line)
    return cols


CBOE_COLUMNS = load_cboe_columns()
FLOW_COLUMNS = CBOE_COLUMNS[CBOE_COLUMNS.index(FLOW_COL_START):]
METADATA_PRICE_COLUMNS = CBOE_COLUMNS[: CBOE_COLUMNS.index(FLOW_COL_START)]
OUTPUT_COLUMNS = list(INTERNAL_COLS) + CBOE_COLUMNS
