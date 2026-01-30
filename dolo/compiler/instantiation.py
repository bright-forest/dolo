"""
Model Validation (spec_0.1h)

Validation helpers for the nest/model representation. The representation itself
is just plain dicts; this module provides structural validation.

Per spec_0.1h, the ModelDict shape is:
    {
        "periods": [PeriodInstance, ...],  # period instances (backward order: terminal first)
        "twisters": [Twister, ...],        # twisters[i] connects periods[i+1] → periods[i]
    }

Where PeriodInstance is:
    {
        "cons_stage": <SymbolicModel>,  # stage objects keyed by stage name
        "port_stage": <SymbolicModel>,
        "connectors": [...],            # optional
    }

And Twister is:
    {"rename": {"a": "k"}}  # or {} for identity

NOTE: This validation could move to dolang+ AST layer if we want it upstream of dolo.
"""

from typing import List


__all__ = [
    "validate_model_dict",
]


def validate_model_dict(model: dict) -> List[str]:
    """
    Validate a model dict for structural correctness.

    Returns a list of warnings (empty if valid).

    Checks:
    - Twisters list length matches number of period boundaries
    - Twisters contain only an optional rename map
    - Period instances are dicts

    Args:
        model: ModelDict with shape {"periods": [...], "twisters": [...]}

    Returns:
        List of warning strings (empty if valid)
    """
    warnings = []

    periods = model.get("periods", [])
    twisters = model.get("twisters", [])

    if not isinstance(periods, list):
        warnings.append(f"Model['periods'] should be a list, got {type(periods).__name__}")
        return warnings

    if not isinstance(twisters, list):
        warnings.append(f"Model['twisters'] should be a list, got {type(twisters).__name__}")
        return warnings

    # Check twister alignment (sequential case)
    expected_twisters = max(len(periods) - 1, 0)
    if len(twisters) != expected_twisters:
        warnings.append(
            f"Expected {expected_twisters} twisters for {len(periods)} periods, got {len(twisters)}"
        )

    # Check twister shapes
    for i, tw in enumerate(twisters):
        if not isinstance(tw, dict):
            warnings.append(f"Twister[{i}] should be a dict, got {type(tw).__name__}")
            continue
        extra_keys = set(tw.keys()) - {"rename"}
        if extra_keys:
            warnings.append(f"Twister[{i}] has unexpected keys: {sorted(extra_keys)}")
        if "rename" in tw and not isinstance(tw["rename"], dict):
            warnings.append(
                f"Twister[{i}].rename should be a dict, got {type(tw['rename']).__name__}"
            )

    # Check period instances are dicts
    for i, period in enumerate(periods):
        if not isinstance(period, dict):
            warnings.append(f"Period[{i}] should be a dict, got {type(period).__name__}")

    return warnings
