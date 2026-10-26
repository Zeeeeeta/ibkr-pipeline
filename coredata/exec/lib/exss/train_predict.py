#!/usr/bin/env python3
"""EXSS XGBoost train/predict via low-level Booster API (prod-compatible)."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from .features import (
    clear_ratio_cache,
    drop_all_nan_features,
    model_feature_candidates,
    prefetch_training_ratios,
    prepare_model_frame,
)
from .labels import attach_labels, training_target
from .config_exp import CURRENT_EXP_CONFIG
from .paths import NO_FILLNA_EXPERIMENT, active_models_dir, model_path
from .postprocess import postprocess_alpha, save_model_meta

try:
    import xgboost as xgb
except ImportError:
    xgb = None  # type: ignore


PROD_PARAMS = {
    'booster': 'gbtree',
    'max_depth': 2,
    'learning_rate': 0.01,
    'subsample': 0.573,
    'objective': 'reg:squarederror',
}


def _require_xgb():
    if xgb is None:
        raise ImportError('Install xgboost==2.0.3 in .venv-opcl for EXSS training')


def load_model_meta(refit_date: str) -> dict:
    meta_path = model_path(refit_date).with_suffix('.meta.json')
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding='utf-8'))


def _prepare_training_frame(train: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    clear_ratio_cache()
    train_dates = sorted(train['quote_ymd'].astype(str).unique())
    prefetch_training_ratios(train_dates)
    labeled_parts = []
    for ymd, grp in train.groupby('quote_ymd'):
        part = prepare_model_frame(grp)
        part = attach_labels(part, str(ymd))
        labeled_parts.append(part)
    frame = pd.concat(labeled_parts, ignore_index=True)
    candidates = model_feature_candidates()
    feature_cols = drop_all_nan_features(frame, candidates)
    if not feature_cols:
        raise ValueError('No usable features after dropping all-NaN columns')
    return frame, feature_cols


def fit_model(train: pd.DataFrame, feature_cols: list[str] | None = None) -> tuple[Any, list[str]]:
    _require_xgb()
    frame, inferred_cols = _prepare_training_frame(train)
    feature_cols = feature_cols or inferred_cols
    y = training_target(frame)
    valid = y.notna()
    if NO_FILLNA_EXPERIMENT:
        w = frame['sqrt_addv_vol']
        valid = valid & w.notna() & np.isfinite(w) & (w > 0)
    frame = frame.loc[valid].copy()
    y = y.loc[frame.index]
    if frame.empty:
        raise ValueError('No training rows after filter/labels')

    if NO_FILLNA_EXPERIMENT:
        X = frame[feature_cols].apply(pd.to_numeric, errors='coerce')
        w = frame['sqrt_addv_vol'].values
    else:
        X = frame[feature_cols].fillna(0.0)
        w = frame['sqrt_addv_vol'].fillna(1.0).values
    params = dict(PROD_PARAMS)
    params['min_child_weight'] = 0.02 * float(np.nansum(w))

    dtrain = xgb.DMatrix(X, label=y, weight=w, feature_names=feature_cols)
    model = xgb.train(params, dtrain, num_boost_round=300)
    return model, feature_cols


def predict_raw(
    model: Any,
    predict: pd.DataFrame,
    feature_cols: list[str] | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    _require_xgb()
    if feature_cols is None:
        feature_cols = model_feature_candidates()
    frame = prepare_model_frame(predict)
    if NO_FILLNA_EXPERIMENT:
        X = frame[feature_cols].apply(pd.to_numeric, errors='coerce')
    else:
        X = frame[feature_cols].fillna(0.0)
    dmat = xgb.DMatrix(X, feature_names=feature_cols)
    raw = pd.Series(model.predict(dmat), index=frame.index, dtype=float)
    return raw, frame


def save_model(
    model: Any,
    refit_date: str,
    *,
    n_train_days: int,
    n_train_rows: int,
    feature_cols: list[str],
) -> str:
    active_models_dir().mkdir(parents=True, exist_ok=True)
    path = str(model_path(refit_date))
    model.save_model(path)
    save_model_meta(refit_date, {
        'refit_date': refit_date,
        'feature_cols': feature_cols,
        'no_fillna_experiment': NO_FILLNA_EXPERIMENT,
        'experiment_config': dict(CURRENT_EXP_CONFIG),
        'n_train_days': n_train_days,
        'n_train_rows': n_train_rows,
        'xgboost_version': xgb.__version__ if xgb else None,
    })
    return path


def load_model(refit_date: str) -> Any:
    _require_xgb()
    path = model_path(refit_date)
    if not path.exists():
        raise FileNotFoundError(f'Model not found: {path}')
    model = xgb.Booster()
    model.load_model(str(path))
    return model


def fit_predict_alpha(train: pd.DataFrame, predict: pd.DataFrame) -> pd.Series:
    model, feature_cols = fit_model(train)
    raw, frame = predict_raw(model, predict, feature_cols=feature_cols)
    return postprocess_alpha(raw, frame)
