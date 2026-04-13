# Dolo+ Compiler Module
#
# Core compilation and instantiation components for Dolo+ models.

# Model validation (spec_0.1h)
from .instantiation import validate_model_dict

# Calibration/Settings functors (spec_0.1c)
from .calibration import (
    load_calibration,
    load_settings,
    calibrate,
    configure,
)

# Methodization functor (spec_0.1d)
from .methodization import (
    load_methodization,
    methodize,
    extract_stage_targets,
    extract_operator_instances,
    emit_methodization_template,
)

from . import stage_factory, spec_factory, period_factory, nest_factory

__all__ = [
    # Validation
    "validate_model_dict",
    # Calibration
    "load_calibration",
    "load_settings",
    "calibrate",
    "configure",
    # Methodization
    "load_methodization",
    "methodize",
    "extract_stage_targets",
    "extract_operator_instances",
    "emit_methodization_template",
    # Factory modules (spec 0.1r)
    "stage_factory",
    "spec_factory",
    "period_factory",
    "nest_factory",
]
