#!/usr/bin/env python3
from pathlib import Path

from ..paths import COREDATA_DIR

PROD_ROOT = COREDATA_DIR / 'data' / 'prod' / 'na' / '3.0'
OPTIONS_OC = PROD_ROOT / 'options_open_close'
EQU_PRICES = COREDATA_DIR / 'data' / 'price'
FEATURES_OUT = COREDATA_DIR / 'data' / 'features'
MODELS_OUT = FEATURES_OUT / 'models'
BARRA = PROD_ROOT / 'barra'
LOCATES = PROD_ROOT / 'locates'
PRICE_60 = COREDATA_DIR / 'data' / 'price_60'


def options_file(root: Path, yyyymmdd: str, name: str) -> Path:
    y, m, d = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:8]
    return root / y / m / d / name


def ib_options_eod(yyyymmdd: str) -> Path:
    return options_file(OPTIONS_OC, yyyymmdd, f'{yyyymmdd}.ib_options_eod.csv.gz')


def mk3_path(yyyymmdd: str) -> Path:
    return options_file(OPTIONS_OC, yyyymmdd, f'{yyyymmdd}.cboe_options_mk3.csv.gz')


def noto_path(yyyymmdd: str) -> Path:
    return options_file(OPTIONS_OC, yyyymmdd, f'{yyyymmdd}.noto_eod_mk2.rev.csv.gz')


def photo_path(yyyymmdd: str) -> Path:
    return options_file(OPTIONS_OC, yyyymmdd, f'{yyyymmdd}.photo_eod_mk2.rev.csv.gz')


def equ_prices_path(yyyymmdd: str) -> Path:
    return EQU_PRICES / yyyymmdd[:4] / f'{yyyymmdd}.equ_prices.csv'


def features_path(yyyymmdd: str) -> Path:
    return FEATURES_OUT / yyyymmdd[:4] / f'{yyyymmdd}.opcl.parq'
