#!/usr/bin/env python3
"""Stage 3: XGBoost refit/predict and alpha post-processing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .paths import MODELS_OUT

try:
    import xgboost as xgb
except Exception:
    xgb = None

try:
    from sklearn.ensemble import HistGradientBoostingRegressor
except Exception:
    HistGradientBoostingRegressor = None


DEFAULT_PARAMS = {
    'n_estimators': 300,
    'max_depth': 2,
    'learning_rate': 0.02,
    'subsample': 0.8,
    'gamma': 0,
    'reg_lambda': 0,
    'tree_method': 'hist',
    'random_state': 0,
}


def target_column(df: pd.DataFrame) -> pd.Series:
    y = df['res_rtn_twap_3nc'].fillna(df['res_rtn_twap_nc'])
    return y.clip(-0.2, 0.25)


def training_weights(df: pd.DataFrame) -> np.ndarray:
    adv = df.get('adv_21d', pd.Series(1.0, index=df.index)).fillna(1)
    ann_var = df.get('annualized_var', pd.Series(0.04, index=df.index)).fillna(0.04).clip(lower=1e-6)
    w = np.sqrt(adv / ann_var) / 4e4
    return w.fillna(1).values


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if 'zscore' in c or c.endswith('_5day')]


def postprocess_alpha(raw: pd.Series, by_date: pd.Series) -> pd.Series:
    out = raw.copy()
    for d in by_date.unique():
        mask = by_date == d
        s = out.loc[mask]
        lo, hi = s.quantile(0.01), s.quantile(0.99)
        s = s.clip(lo, hi)
        s = s - s.mean()
        out.loc[mask] = s
    return out


def _prepare_training_frame(train: pd.DataFrame, feature_cols: list) -> tuple[pd.DataFrame, pd.Series, np.ndarray]:
    train = train.loc[train.get('prediction_valid_sample', train.get('valid_sample', True))].copy()
    y_tr = target_column(train)
    train = train.loc[y_tr.notna()].copy()
    y_tr = y_tr.loc[train.index]
    if train.empty:
        raise ValueError('No training rows with valid target labels')
    X_tr = train[feature_cols].fillna(0.5)
    w = training_weights(train)
    return X_tr, y_tr, w


def fit_model(train: pd.DataFrame, feature_cols: list) -> Any:
    """Fit and return a frozen model artifact (XGBoost or sklearn fallback)."""
    X_tr, y_tr, w = _prepare_training_frame(train, feature_cols)
    if xgb is not None:
        min_child = max(1.0, w.sum() * 0.01)
        model = xgb.XGBRegressor(**DEFAULT_PARAMS, min_child_weight=min_child)
        model.fit(X_tr, y_tr, sample_weight=w)
        backend = 'xgboost'
    elif HistGradientBoostingRegressor is not None:
        model = HistGradientBoostingRegressor(
            max_depth=2, learning_rate=0.02, max_iter=300, random_state=0,
        )
        model.fit(X_tr, y_tr, sample_weight=w)
        backend = 'sklearn'
    else:
        raise ImportError('Install xgboost (needs libomp on Mac) or scikit-learn')
    model.opcl_backend = backend  # type: ignore[attr-defined]
    return model


def predict_with_model(
    model: Any,
    predict: pd.DataFrame,
    feature_cols: list,
) -> pd.Series:
    predict = predict.copy()
    X_pred = predict[feature_cols].fillna(0.5)
    raw = pd.Series(model.predict(X_pred), index=predict.index, dtype=float)
    date_key = predict.get('quote_ymd', predict.get('date', pd.Series(0, index=predict.index)))
    return postprocess_alpha(raw, date_key)


def model_bundle_path(refit_date: str) -> Path:
    return MODELS_OUT / refit_date[:4] / f'{refit_date}.opcl.model.joblib'


def save_model_bundle(
    model: Any,
    feature_cols: list,
    refit_date: str,
    *,
    train_years: float | None = None,
    n_train_days: int | None = None,
    n_train_rows: int | None = None,
) -> Path:
    import joblib

    out = model_bundle_path(refit_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        'refit_date': refit_date,
        'feature_cols': feature_cols,
        'backend': getattr(model, 'opcl_backend', 'unknown'),
        'train_years': train_years,
        'n_train_days': n_train_days,
        'n_train_rows': n_train_rows,
    }
    joblib.dump({'model': model, 'meta': meta}, out)
    meta_path = out.with_suffix('.meta.json')
    meta_path.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    return out


def list_saved_refit_dates(through: str | None = None) -> list[str]:
    dates: list[str] = []
    if not MODELS_OUT.exists():
        return dates
    for path in MODELS_OUT.glob('*/*.opcl.model.joblib'):
        ymd = path.name.split('.')[0]
        if through is None or ymd <= through:
            dates.append(ymd)
    return sorted(dates)


def latest_saved_refit_date(for_date: str) -> str | None:
    saved = list_saved_refit_dates(for_date)
    return saved[-1] if saved else None


def load_model_bundle(refit_date: str) -> tuple[Any, list[str], dict]:
    import joblib

    path = model_bundle_path(refit_date)
    if not path.exists():
        raise FileNotFoundError(f'Frozen model not found for refit {refit_date}: {path}')
    bundle = joblib.load(path)
    meta = bundle.get('meta', {})
    return bundle['model'], meta.get('feature_cols', []), meta


def fit_predict(
    train: pd.DataFrame,
    predict: pd.DataFrame,
    feature_cols: list,
) -> pd.Series:
    model = fit_model(train, feature_cols)
    return predict_with_model(model, predict, feature_cols)
