"""
Calibration and Settings Functors (spec_0.1c §4.7)

Implements the functorial stage composition pattern:
  stage₀ (syntactic) → calibrate() → stage₁ (calibrated)
  stage₁ (calibrated) → configure() → stage₂ (configured)

Each functor returns a NEW stage object without mutating the original.

Usage:
    from dolo.compiler.model import SymbolicModel
    from dolo.compiler.calibration import calibrate, configure

    # Load syntactic stage
    stage = SymbolicModel(yaml.compose(open("stage.yaml").read()))

    # Apply functors (each returns a new stage)
    calibrated = calibrate(stage, "calibration.yaml")
    configured = configure(calibrated, "settings.yaml")

    # Access attached data
    calibrated.calibration  # {'β': 0.96, ...}
    configured.settings     # {'n_w': 100, ...}
"""

from pathlib import Path
from typing import Union, Dict, Any
import yaml

__all__ = [
    "load_calibration",
    "load_settings",
    "calibrate",
    "configure",
]


# -----------------------------------------------------------------------------
# Raw Loaders (return plain dicts)
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

    Example:
        >>> calib = load_calibration("calibration.yaml")
        >>> calib['beta']
        0.96
    """
    data = _load_source(source)

    # Unwrap 'calibration:' key if present
    if isinstance(data, dict) and 'calibration' in data:
        data = data['calibration']

    # Extract parameters only (ignore settings)
    if isinstance(data, dict) and 'parameters' in data:
        return dict(data['parameters'])

    # Remove settings if present in flat dict
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

    Example:
        >>> settings = load_settings("settings.yaml")
        >>> settings['n_w']
        200
    """
    data = _load_source(source)

    # Unwrap 'settings:' key if present
    if isinstance(data, dict) and 'settings' in data:
        return dict(data['settings'])

    # Handle calibration file with split format
    if isinstance(data, dict) and 'calibration' in data:
        calib = data['calibration']
        if isinstance(calib, dict) and 'settings' in calib:
            return dict(calib['settings'])

    # Return as-is if it looks like flat settings
    return data


def _load_source(source: Union[str, Path, dict]) -> dict:
    """Load data from file path or return dict as-is."""
    if isinstance(source, dict):
        return source

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# -----------------------------------------------------------------------------
# Stage Functors (spec_0.1c §4.7)
# -----------------------------------------------------------------------------
# These functions implement the "calibration functor" and "settings functor"
# from the spec. They return NEW stage objects with attachments, preserving
# the original stage unchanged (functorial composition).


def calibrate(stage, calibration_source: Union[str, Path, dict]):
    """
    Apply calibration functor to a stage (spec_0.1c §4.7).

    Returns a NEW stage object with `.calibration` attached.
    The original stage is not mutated.

    Args:
        stage: SymbolicModel (syntactic stage with symbols/symbols_math)
        calibration_source: Path to calibration YAML, or dict

    Returns:
        New SymbolicModel with `.calibration` populated

    Example:
        >>> from dolo.compiler.model import SymbolicModel
        >>> from dolo.compiler.calibration import calibrate
        >>> stage = SymbolicModel(yaml.compose(open("stage.yaml").read()))
        >>> calibrated = calibrate(stage, "calibration.yaml")
        >>> calibrated.calibration['β']
        0.96
        >>> stage.calibration  # Original unchanged
        None
    """
    import copy

    # Shallow copy preserves computed caches (__symbols__, __symbols_math__, etc.)
    new_stage = copy.copy(stage)

    # Load and attach calibration
    calib_data = load_calibration(calibration_source)
    new_stage._calibration = calib_data

    return new_stage


def configure(stage, settings_source: Union[str, Path, dict]):
    """
    Apply settings functor to a stage (spec_0.1c §4.7).

    Returns a NEW stage object with `.settings` attached.
    The original stage is not mutated.

    Args:
        stage: SymbolicModel (possibly already calibrated)
        settings_source: Path to settings YAML, or dict

    Returns:
        New SymbolicModel with `.settings` populated

    Example:
        >>> configured = configure(calibrated, "settings.yaml")
        >>> configured.settings['n_w']
        100
    """
    import copy

    new_stage = copy.copy(stage)

    # Load and attach settings
    settings_data = load_settings(settings_source)
    new_stage._settings = settings_data

    return new_stage
