# Dolo+ Compiler Module
#
# Core compilation and instantiation components for Dolo+ models.

# Period instantiation (spec_0.1h)
from .instantiation import (
    make_connector,
    make_terminal_relabel,
    make_twister,
    load_period_template,
    instantiate_period,
    make_model_dict,
    validate_model_dict,
)

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

__all__ = [
    # Instantiation
    "make_connector",
    "make_terminal_relabel",
    "make_twister",
    "load_period_template",
    "instantiate_period",
    "make_model_dict",
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
]
