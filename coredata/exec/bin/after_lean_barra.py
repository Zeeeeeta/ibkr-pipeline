#!/usr/bin/env python3
"""
Wait for Lean Barra batch to finish, then git commit + push.

Example::

    nohup python3 after_lean_barra.py >> coredata/data/ref/after_lean_barra.log 2>&1 &
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

_BIN = Path(__file__).resolve().parent
_REPO = _BIN.parents[2]
sys.path.insert(0, str(_BIN.parent))

from lib.lean_barra.paths import LEAN_BARRA
from lib.opcl.calendar import load_trading_days

LOG = _REPO / 'coredata' / 'data' / 'ref' / 'after_lean_barra.log'
BATCH_LOG = _REPO / 'coredata' / 'data' / 'ref' / 'lean_barra_batch.log'


def parse_args():
    p = argparse.ArgumentParser(description='Post Lean Barra git push')
    p.add_argument('--start', default='20170522')
    p.add_argument('--end', default='20260402')
    p.add_argument('--poll-sec', type=int, default=120)
    p.add_argument('--min-files', type=int, default=0,
                   help='Override min parquet count (0 = all trading days in range)')
    p.add_argument('--skip-git', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def _log(msg: str) -> None:
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def _lean_running() -> bool:
    out = subprocess.run(['ps', 'aux'], capture_output=True, text=True).stdout
    return any(
        'build_lean_barra_range' in line
        for line in out.splitlines()
        if 'grep' not in line
    )


def _expected_days(start: str, end: str) -> int:
    return len(load_trading_days(start, end, feature_fallback=False))


def _parquet_count() -> int:
    if not LEAN_BARRA.exists():
        return 0
    return sum(1 for _ in LEAN_BARRA.rglob('*.lean_barra_exposures.parq'))


def _batch_progress() -> tuple[int, int, bool]:
    """Return (done, total, saw_done_line) from batch log."""
    if not BATCH_LOG.exists():
        return 0, 0, False
    text = BATCH_LOG.read_text(encoding='utf-8', errors='replace')
    saw_done = bool(re.search(r'^done ok=\d+', text, re.MULTILINE))
    matches = re.findall(r'\[(\d+)/(\d+)\]', text)
    if not matches:
        return 0, 0, saw_done
    done, total = matches[-1]
    return int(done), int(total), saw_done


def _wait_for_lean_barra(args) -> None:
    expected = args.min_files or _expected_days(args.start, args.end)
    _log(f'waiting for Lean Barra batch ({args.start}..{args.end}, expect>={expected} files)')
    while True:
        running = _lean_running()
        files = _parquet_count()
        done, total, saw_done = _batch_progress()
        _log(
            f'poll running={running} files={files}/{expected} '
            f'log_progress={done}/{total} saw_done={saw_done}'
        )
        if not running and saw_done and files >= expected:
            _log('Lean Barra batch complete')
            return
        if not running and files >= expected and done >= total and total > 0:
            _log('Lean Barra batch complete (progress reached total)')
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
        'coredata/data/prod/na/3.0/lean_barra/',
        'coredata/data/ref/lean_barra_batch.log',
        'coredata/data/ref/after_lean_barra.log',
    ]
    _run(['git', 'add', *paths], dry_run=args.dry_run)
    if not args.dry_run:
        st = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=_REPO)
        if st.returncode != 0:
            _run([
                'git', 'commit', '-m',
                'Add 9y Lean Barra exposure batch for OPCL labels.',
            ], dry_run=False)
        else:
            _log('nothing to commit')
    _run(['git', 'push'], dry_run=args.dry_run)


def main():
    args = parse_args()
    _wait_for_lean_barra(args)
    if not args.skip_git:
        _git_push(args)
    _log('after_lean_barra finished')


if __name__ == '__main__':
    main()
