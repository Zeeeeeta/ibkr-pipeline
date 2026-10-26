#!/usr/bin/env python3
"""EXSS path conventions and venue constants."""

from pathlib import Path

from ..paths import COREDATA_DIR
from ..opcl.paths import PROD_ROOT

SHORT_SALE = PROD_ROOT / 'short_sale'
EXSS_FEATURES = COREDATA_DIR / 'data' / 'exss_features'
EXSS_MODELS = COREDATA_DIR / 'data' / 'exss_models'
EXSS_OUT = COREDATA_DIR / 'data' / 'exss_out'

# Lossless experiment: no feature fillna; FINRA trio + NYSE FTP only.
NO_FILLNA_EXPERIMENT = True
FINRA_RATIO_FEATURES = [
    'ratio_finra_nasdaq', 'ratio_finra_nyse', 'ratio_finra_orf',
]
NYSE_FTP_RATIO_FEATURES = ['ratio_nyse', 'ratio_nyse_arca']
EXPERIMENT_RATIO_BASES = FINRA_RATIO_FEATURES + NYSE_FTP_RATIO_FEATURES
EXPERIMENT_MODELS_SUBDIR = 'finra_nyse_no_fillna'
SID_MAP_PATH = COREDATA_DIR / 'data' / 'ref' / 'symbol_sid_full.csv'

# 8 lit exchanges (shortsale.rev) + 3 FINRA (shvol.rev)
LIT_EXCHANGES = (
    'bats', 'baty', 'edga', 'edgx',
    'nasdaq_bx', 'nasdaq', 'nyse_arca', 'nyse',
)
FINRA_EXCHANGES = ('finra_nasdaq', 'finra_nyse', 'finra_orf')
ALL_EXCHANGES = LIT_EXCHANGES + FINRA_EXCHANGES

# Base ratio columns saved in step1 (12 venues + aggregate)
RATIO_BASE_COLS = [f'ratio_{ex}' for ex in ALL_EXCHANGES] + ['ratio_all']

# 12 features used in prod XGBoost model
MODEL_FEATURES = [
    'ratio_bats', 'ratio_baty', 'ratio_edga', 'ratio_nasdaq_bx',
    'ratio_nasdaq', 'ratio_finra_nasdaq',
    'ratio_bats_1_d', 'ratio_baty_1_d', 'ratio_edga_1_d',
    'ratio_nasdaq_bx_1_d', 'ratio_nasdaq_1_d', 'ratio_finra_nasdaq_1_d',
]

EWM_HALFLIVES = (1, 3, 10)
EWM_LOOKBACK_DAYS = 252
MODEL_LAG_TRADING_DAYS = 15


def experiment_feature_candidates() -> list[str]:
    return EXPERIMENT_RATIO_BASES + [f'{b}_1_d' for b in EXPERIMENT_RATIO_BASES]


def active_models_dir() -> Path:
    from .config_exp import experiment_models_dir, is_ablation_active

    if is_ablation_active():
        return experiment_models_dir()
    if NO_FILLNA_EXPERIMENT:
        return EXSS_MODELS / EXPERIMENT_MODELS_SUBDIR
    return EXSS_MODELS


def short_sale_path(yyyymmdd: str, exchange: str) -> Path:
    suffix = 'shvol' if exchange in FINRA_EXCHANGES else 'shortsale'
    return SHORT_SALE / yyyymmdd[:4] / f'{yyyymmdd}.{exchange}_{suffix}.rev.csv.gz'


def step1_path(yyyymmdd: str) -> Path:
    return EXSS_FEATURES / yyyymmdd[:4] / f'{yyyymmdd}.exss_step1.parq'


def step2_path(yyyymmdd: str) -> Path:
    return EXSS_FEATURES / yyyymmdd[:4] / f'{yyyymmdd}.exss_step2.parq'


def model_path(refit_date: str) -> Path:
    return active_models_dir() / f'{refit_date}.exss_model.json'


def alpha_path(yyyymmdd: str) -> Path:
    return EXSS_OUT / f'{yyyymmdd}.exss_alpha.csv'
