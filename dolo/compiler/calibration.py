"""
Calibration and Settings — source-level I/O + re-exports (spec_0.1c §4.7).

The stage verbs (calibrate, configure) live in stage_factory/.
This file keeps the source-level I/O helpers (load_calibration,
load_settings) and re-exports the verbs for backward compatibility.
"""

from pathlib import Path
from typing import Union
import yaml

# Re-export stage verbs (spec 0.1r — code lives in stage_factory/)
from .stage_factory.calibrate import calibrate  # noqa: F401
from .stage_factory.configure import configure  # noqa: F401

__all__ = [
    "load_calibration",
    "load_settings",
    "calibrate",
    "configure",
]


# -----------------------------------------------------------------------------
# Raw Loaders (return plain dicts) — source-level I/O, stay here
# -----------------------------------------------------------------------------

def load_calibration(source: Union[str, Path, dict]) -> dict:
    """
    Load calibration data from file or dict.

    Accepts:
      - Path to YAML file
      - Dict with flat format: {beta: 0.96, delta: 0.03}
      - Dict with nested format: {calibration: {parameters: {...}}}
      - Dict with split format: {parameters: {...}, settings: {...}}

    Returns:
      Flat dict of calibration values (parameters only, no settings).
    """
    data = _load_source(source)

    if isinstance(data, dict) and 'calibration' in data:
        data = data['calibration']

    if isinstance(data, dict) and 'parameters' in data:
        return dict(data['parameters'])

    if isinstance(data, dict) and 'settings' in data:
        data = {k: v for k, v in data.items() if k != 'settings'}

    return data


def load_settings(source: Union[str, Path, dict]) -> dict:
    """
    Load settings data from file or dict.

    Accepts:
      - Path to YAML file
      - Dict with flat format: {n_w: 200, tol: 1e-8}
      - Dict with nested format: {settings: {...}}
      - Dict with split format (calibration file): {parameters: {...}, settings: {...}}

    Returns:
      Flat dict of settings values.
    """
    data = _load_source(source)

    if isinstance(data, dict) and 'settings' in data:
        return dict(data['settings'])

    if isinstance(data, dict) and 'calibration' in data:
        calib = data['calibration']
        if isinstance(calib, dict) and 'settings' in calib:
            return dict(calib['settings'])

    return data


def _load_source(source: Union[str, Path, dict]) -> dict:
    """Load data from file path or return dict as-is."""
    import types
    if isinstance(source, (dict, types.MappingProxyType)):
        return dict(source) if isinstance(source, types.MappingProxyType) else source

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
