#!/usr/bin/env python3
"""
Wait for equ backfill to finish, then git push and start Lean Barra batch.

Example::

    nohup python3 after_equ_backfill.py >> coredata/data/ref/after_equ_backfill.log 2>&1 &
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_BIN = Path(__file__).resolve().parent
_REPO = _BIN.parents[2]
sys.path.insert(0, str(_BIN.parent))

PROGRESS_CSV = _REPO / 'coredata' / 'data' / 'ref' / 'equ_backfill_progress.csv'
LOG = _REPO / 'coredata' / 'data' / 'ref' / 'after_equ_backfill.log'
LEAN_LOG = _REPO / 'coredata' / 'data' / 'ref' / 'lean_barra_batch.log'
TOTAL_SYMBOLS = 1688


def parse_args():
    p = argparse.ArgumentParser(description='Post-backfill git push + Lean Barra batch')
    p.add_argument('--min-progress', type=int, default=1680,
                   help='Min progress CSV rows before considering backfill done')
    p.add_argument('--poll-sec', type=int, default=60)
    p.add_argument('--lean-start', default='20170522',
                   help='First Lean Barra date (9y OPCL train start)')
    p.add_argument('--lean-end', default='20260402')
    p.add_argument('--history-days', type=int, default=1100)
    p.add_argument('--skip-git', action='store_true')
    p.add_argument('--skip-lean', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def _log(msg: str) -> None:
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def _backfill_running() -> bool:
    out = subprocess.run(['ps', 'aux'], capture_output=True, text=True).stdout
    return any(
        'fetch_equ_symbols' in line or 'backfill_equ_prices' in line
        for line in out.splitlines()
        if 'grep' not in line
    )


def _progress_rows() -> int:
    if not PROGRESS_CSV.exists():
        return 0
    return max(0, sum(1 for _ in PROGRESS_CSV.open()) - 1)


def _wait_for_backfill(args) -> None:
    _log('waiting for equ backfill to finish')
    while True:
        running = _backfill_running()
        rows = _progress_rows()
        _log(f'poll running={running} progress_rows={rows}/{TOTAL_SYMBOLS}')
        if not running and rows >= args.min_progress:
            _log('backfill complete')
            return
        time.sleep(args.poll_sec)


def _run(cmd: list[str], *, dry_run: bool = False) -> None:
    _log('>> ' + ' '.join(cmd))
    if dry_run:
        return
    subprocess.check_call(cmd, cwd=str(_REPO))


def _git_push(args) -> None:
    _log('git add + commit + push')
    _run(['git', 'status', '--short'], dry_run=args.dry_run)
    paths = [
        'coredata/exec/',
        'coredata/data/ref/equ_backfill_progress.csv',
        'coredata/data/ref/equ_backfill.log',
        'coredata/data/ref/equ_backfill_hourly_reports.log',
        'coredata/data/ref/after_equ_backfill.log',
        'coredata/data/price/',
    ]
    _run(['git', 'add', *paths], dry_run=args.dry_run)
    # Commit only if there are staged changes
    if not args.dry_run:
        st = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=_REPO)
        if st.returncode != 0:
            _run([
                'git', 'commit', '-m',
                'Complete full-universe equ price backfill and add Lean Barra batch tooling.',
            ], dry_run=False)
        else:
            _log('nothing to commit')
    _run(['git', 'push'], dry_run=args.dry_run)


def _start_lean_batch(args) -> None:
    lean = _BIN / 'build_lean_barra_range.py'
    cmd = [
        sys.executable, str(lean),
        '--inner', '--no-caffeinate',
        '--start', args.lean_start,
        '--end', args.lean_end,
        '--history-days', str(args.history_days),
        '--skip-existing',
        '--no-csv',
    ]
    _log('starting Lean Barra batch')
    if args.dry_run:
        _log('>> ' + ' '.join(cmd))
        return
    LEAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LEAN_LOG.open('a', encoding='utf-8') as fh:
        fh.write(f'\n{time.strftime("%Y-%m-%d %H:%M:%S")} launched after_equ_backfill\n')
        subprocess.Popen(
            ['caffeinate', '-dimsu', *cmd],
            cwd=str(_REPO),
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    _log(f'Lean Barra batch running; log={LEAN_LOG}')


def main():
    args = parse_args()
    _wait_for_backfill(args)
    if not args.skip_git:
        _git_push(args)
    if not args.skip_lean:
        _start_lean_batch(args)
    _log('after_equ_backfill finished')


if __name__ == '__main__':
    main()
