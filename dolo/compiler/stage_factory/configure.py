"""Settings functor — attaches numerical settings to a stage (spec_0.1c §4.7)."""

import copy
from pathlib import Path
from typing import Union


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
    from dolo.compiler.calibration import load_settings

    new_stage = copy.copy(stage)
    settings_data = load_settings(settings_source)
    new_stage._settings = settings_data
    return new_stage
