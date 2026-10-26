#!/usr/bin/env python3
"""IB connection helpers."""

import logging
import os

from ib_async import IB, StartupFetchNONE

# TWS: paper 7497, live 7496.  IB Gateway: paper 4002, live 4001.
DEFAULT_HOST = os.environ.get('IB_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('IB_PORT', '7497'))


def silence_ib_logs():
    logging.getLogger().handlers = []
    for name in ('ib_async', 'ib_async.wrapper', 'ib_async.client', 'ib_async.ib'):
        log = logging.getLogger(name)
        log.setLevel(logging.CRITICAL)
        log.propagate = False
        log.handlers = []


def connect_ib(
    client_id: int = 5,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: int = 60,
    request_timeout: int = 180,
    log_errors: bool = False,
) -> IB:
    silence_ib_logs()
    ib = IB()
    ib.RequestTimeout = request_timeout
    ib.connect(
        host,
        port,
        clientId=client_id,
        timeout=timeout,
        readonly=True,
        fetchFields=StartupFetchNONE,
    )
    if log_errors:
        def _log(reqId, errorCode, errorString, contract=None):
            if errorCode not in (2104, 2106, 2158):  # connection OK informational
                print(f'IB {errorCode}: {errorString}')
        ib.errorEvent += _log
    else:
        ib.client.apiError = lambda reqId, errorCode, errorString, contract=None: None
        ib.wrapper.error = lambda reqId, errorCode, errorString, contract=None: None
    return ib
