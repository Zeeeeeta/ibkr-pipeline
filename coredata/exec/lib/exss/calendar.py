#!/usr/bin/env python3
"""Annual refit dates and model lag for EXSS."""

from __future__ import annotations

from datetime import datetime

from ..opcl.calendar import load_trading_days
from .paths import EXSS_MODELS, MODEL_LAG_TRADING_DAYS, active_models_dir, model_path, step2_path


def list_step2_dates(start: str, end: str) -> list[str]:
    out = []
    dt = datetime.strptime(start, '%Y%m%d')
    end_dt = datetime.strptime(end, '%Y%m%d')
    while dt <= end_dt:
        ymd = dt.strftime('%Y%m%d')
        if step2_path(ymd).exists():
            out.append(ymd)
        dt = datetime.fromordinal(dt.toordinal() + 1)
    return sorted(out)


def year_end_trading_dates(start: str, end: str) -> list[str]:
    """Last trading day of each calendar year in range."""
    days = load_trading_days(start, end, feature_fallback=False)
    if not days:
        days = list_step2_dates(start, end)
    by_year: dict[int, list[str]] = {}
    for d in days:
        by_year.setdefault(int(d[:4]), []).append(d)
    return [max(v) for y, v in sorted(by_year.items())]


def list_saved_models(through: str | None = None) -> list[str]:
    root = active_models_dir()
    if not root.exists():
        return []
    dates = []
    for p in root.glob('*.exss_model.json'):
        ymd = p.name.split('.')[0]
        if through is None or ymd <= through:
            dates.append(ymd)
    return sorted(dates)


def active_model_date(predict_date: str, refit_dates: list[str]) -> str | None:
    """
    Prod rule: most recent model with refit_date <= predict_date - 15 trading days.
    """
    days = load_trading_days('19900101', predict_date, feature_fallback=False)
    if predict_date not in days:
        days = sorted(set(days + [predict_date]))
    try:
        idx = days.index(predict_date)
    except ValueError:
        idx = len(days) - 1
    lag_idx = max(0, idx - MODEL_LAG_TRADING_DAYS)
    cutoff = days[lag_idx]
    prior = [d for d in refit_dates if d <= cutoff]
    return max(prior) if prior else None


def training_dates_before(refit_date: str, available: list[str]) -> list[str]:
    return sorted(d for d in available if d < refit_date)
