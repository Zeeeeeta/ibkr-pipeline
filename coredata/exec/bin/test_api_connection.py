#!/usr/bin/env python3
"""Smoke test IB Gateway / TWS API connection."""

import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.ib_connect import DEFAULT_HOST, DEFAULT_PORT, connect_ib


def main():
    print(f'Connecting to {DEFAULT_HOST}:{DEFAULT_PORT} ...')
    print('  (Gateway paper=4002, TWS paper=7497 — set IB_PORT env)')
    try:
        ib = connect_ib(client_id=10, log_errors=True, request_timeout=60)
        if ib.isConnected():
            print('Connected.')
            accounts = ib.wrapper.accounts if ib.wrapper.accounts else []
            if accounts:
                print(f'Account: {accounts[0]}')
            ib.disconnect()
            print('OK')
    except Exception as e:
        print('Connection failed.')
        print('1. IB Gateway (or TWS) logged in?')
        print(f'2. API enabled on port {DEFAULT_PORT}?')
        print('3. See coredata/exec/schemas/IB_GATEWAY.md')
        print(f'Error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
