"""Lean Barra — localized style factor exposure engine."""

from .connectors import (
    ols_design_matrix,
    optimizer_constraint_specs,
    residualize_alpha,
)
from .factors import STYLE_FACTORS, compute_raw_factors
from .pipeline import build_daily_exposures, run_lean_barra, write_exposures
from .residualize import (
    estimate_factor_returns,
    parity_checklist,
    residualize_merged,
    residualize_returns,
)

__all__ = [
    'STYLE_FACTORS',
    'build_daily_exposures',
    'compute_raw_factors',
    'estimate_factor_returns',
    'ols_design_matrix',
    'optimizer_constraint_specs',
    'parity_checklist',
    'residualize_alpha',
    'residualize_merged',
    'residualize_returns',
    'run_lean_barra',
    'write_exposures',
]
