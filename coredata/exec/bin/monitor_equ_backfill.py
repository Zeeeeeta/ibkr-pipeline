#!/usr/bin/env python3
"""Hourly equ backfill status report."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(_BIN.parent))

from lib.opcl.equ_fetch import EQU_BACKFILL_PROGRESS

LOG = EQU_BACKFILL_PROGRESS.parent / 'equ_backfill.log'
REPORT = EQU_BACKFILL_PROGRESS.parent / 'equ_backfill_hourly_reports.log'
TOTAL = 1688


def _running() -> tuple[bool, list[str]]:
    out = subprocess.run(['ps', 'aux'], capture_output=True, text=True).stdout
    procs = [
        l for l in out.splitlines()
        if ('backfill_equ' in l or 'fetch_equ_symbols' in l) and 'grep' not in l
    ]
    return bool(procs), procs


def _log_index() -> int:
    if not LOG.exists():
        return 0
    nums = [int(m.group(1)) for m in re.finditer(r'\[(\d+)/1688\]', LOG.read_text())]
    return max(nums) if nums else 0


def _eta_hours(done: int, elapsed_min: float) -> float | None:
    if done <= 0 or elapsed_min <= 0:
        return None
    rate = done / elapsed_min
    if rate <= 0:
        return None
    return (TOTAL - done) / rate / 60


def build_report() -> str:
    now = datetime.now().astimezone()
    running, procs = _running()
    done = 0
    status: dict[str, int] = {}
    last_sym = last_stat = 'n/a'

    if EQU_BACKFILL_PROGRESS.exists():
        df = pd.read_csv(EQU_BACKFILL_PROGRESS)
        done = len(df)
        status = df['status'].value_counts().to_dict()
        if not df.empty:
            last = df.iloc[-1]
            last_sym = str(last['symbol'])
            last_stat = str(last['status'])

    pct = 100 * done / TOTAL
    log_idx = _log_index()
    log_age_s = None
    log_tail = 'n/a'
    if LOG.exists():
        log_age_s = now.timestamp() - LOG.stat().st_mtime
        log_tail = LOG.read_text().strip().splitlines()[-1][:100]

    elapsed_min = None
    eta_h = None
    if LOG.exists():
        start_ts = getattr(LOG.stat(), 'st_birthtime', LOG.stat().st_ctime)
        elapsed_min = (now.timestamp() - start_ts) / 60
        # ETA from log scan index when actively fetching; else from CSV completion.
        pace_basis = log_idx if running and log_idx > done else done
        eta_h = _eta_hours(pace_basis, elapsed_min)

    lines = [
        f'=== Equ backfill hourly report ===',
        f'time: {now.strftime("%Y-%m-%d %H:%M:%S %Z")}',
        f'running: {"YES" if running else "NO"}',
        f'progress_csv: {done}/{TOTAL} ({pct:.1f}%)',
        f'status: {status}',
        f'log_scan_index: [{log_idx}/{TOTAL}]',
        f'last_completed: {last_sym} ({last_stat})',
    ]
    if log_age_s is not None:
        lines.append(f'log_updated: {log_age_s:.0f}s ago')
    lines.append(f'log_tail: {log_tail}')
    if elapsed_min is not None:
        lines.append(f'elapsed: {elapsed_min:.0f} min')
    if eta_h is not None:
        finish = now.timestamp() + eta_h * 3600
        finish_dt = datetime.fromtimestamp(finish).astimezone()
        lines.append(f'eta: ~{eta_h:.1f} h (around {finish_dt.strftime("%Y-%m-%d %H:%M")})')
    else:
        lines.append('eta: n/a')
    if running:
        for p in procs[:2]:
            parts = p.split()
            lines.append(f'process: pid={parts[1]} cpu={parts[2]}%')
    return '\n'.join(lines)


def main():
    report = build_report()
    print(report)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open('a', encoding='utf-8') as fh:
        fh.write(report + '\n\n')


if __name__ == '__main__':
    main()
