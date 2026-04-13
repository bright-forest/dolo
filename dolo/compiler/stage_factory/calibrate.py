"""Calibration functor — attaches parameter values to a stage (spec_0.1c §4.7)."""

import copy
from pathlib import Path
from typing import Union


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
        >>> from dolo.compiler.stage_factory import calibrate
        >>> calibrated = calibrate(stage, "calibration.yaml")
        >>> calibrated.calibration['β']
        0.96
        >>> stage.calibration  # Original unchanged
        None
    """
    from dolo.compiler.calibration import load_calibration

    new_stage = copy.copy(stage)
    calib_data = load_calibration(calibration_source)
    new_stage._calibration = calib_data
    return new_stage
