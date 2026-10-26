#!/usr/bin/env python3
"""EXSS ablation grid config (isolated from prod paths)."""

from __future__ import annotations

import itertools
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import EXSS_MODELS, EXSS_OUT

EXPERIMENT_GRID = {
    'direction': ['long_short', 'long_only'],
    'htb_filter': [False, True],
    'feature_transform': ['raw', 'zscore_20d'],
    'label_window': ['res_rtn_twap_3nc', 'res_rtn_1d_oc'],
}

DEFAULT_EXP_CONFIG: dict[str, Any] = {
    'direction': 'long_short',
    'htb_filter': False,
    'feature_transform': 'raw',
    'label_window': 'res_rtn_twap_3nc',
}

CURRENT_EXP_CONFIG: dict[str, Any] = deepcopy(DEFAULT_EXP_CONFIG)
ABLATION_MODELS_ROOT = EXSS_MODELS / 'ablation'
EXPERIMENTS_SUMMARY_CSV = EXSS_OUT / 'experiments_summary.csv'
ZSCORE_ROLLING_DAYS = 20


def get_experiment_combinations() -> list[dict[str, Any]]:
    keys = EXPERIMENT_GRID.keys()
    return [dict(zip(keys, combo)) for combo in itertools.product(*EXPERIMENT_GRID.values())]


def experiment_slug(cfg: dict[str, Any]) -> str:
    return '_'.join([
        cfg['direction'],
        'htb' if cfg['htb_filter'] else 'nohtb',
        cfg['feature_transform'],
        cfg['label_window'].replace('res_rtn_', ''),
    ])


def experiment_models_dir(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or CURRENT_EXP_CONFIG
    return ABLATION_MODELS_ROOT / experiment_slug(cfg)


def is_ablation_active() -> bool:
    if os.environ.get('EXSS_EXP_CONFIG', '').strip():
        return True
    return CURRENT_EXP_CONFIG != DEFAULT_EXP_CONFIG


def set_experiment_config(cfg: dict[str, Any]) -> dict[str, Any]:
    global CURRENT_EXP_CONFIG
    merged = deepcopy(DEFAULT_EXP_CONFIG)
    merged.update(cfg)
    CURRENT_EXP_CONFIG = merged
    os.environ['EXSS_EXP_CONFIG'] = json.dumps(merged, sort_keys=True)
    return CURRENT_EXP_CONFIG


def clear_experiment_config() -> dict[str, Any]:
    global CURRENT_EXP_CONFIG
    CURRENT_EXP_CONFIG = deepcopy(DEFAULT_EXP_CONFIG)
    os.environ.pop('EXSS_EXP_CONFIG', None)
    return CURRENT_EXP_CONFIG


def load_experiment_config_from_env() -> dict[str, Any] | None:
    raw = os.environ.get('EXSS_EXP_CONFIG', '').strip()
    if not raw:
        return None
    return set_experiment_config(json.loads(raw))


load_experiment_config_from_env()
