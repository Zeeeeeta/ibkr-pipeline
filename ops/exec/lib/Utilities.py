#!/usr/bin/env python3
"""Local substitute for /q/common/exec/lib/Utilities."""


def niceNum(val):
    """Format a numeric value for compact terminal display."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)

    if v != v:  # NaN
        return str(val)

    av = abs(v)
    if av >= 1e12:
        return f'{v / 1e12:.4g}T'
    if av >= 1e9:
        return f'{v / 1e9:.4g}B'
    if av >= 1e6:
        return f'{v / 1e6:.4g}M'
    if av >= 1e3:
        return f'{v / 1e3:.4g}K'
    return f'{v:.6g}'
