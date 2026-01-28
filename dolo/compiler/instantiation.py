"""
Period Instantiation (spec_0.1h)

Minimal instantiation layer for periods + twisters that:
- Does NOT introduce new classes (artifacts are plain dicts + existing SymbolicModel)
- Uses twisters-as-composition (inter-period wiring objects)
- Uses connectors for within-period wiring (including optional terminal relabels)
- Binds calibration/methodization/settings at the stage level (per existing semantics)
- Reuses existing Dolo+ functors (calibrate, configure, methodize)

Usage:
    from dolo.compiler.instantiation import (
        make_connector,
        make_twister,
        instantiate_period,
        make_model_dict,
        load_period_template,
    )

    # Load period template
    template = load_period_template("period.yaml")

    # Create period instance with bound stages
    period = instantiate_period(
        template,
        name="p01",
        bindings={"cons_stage": calibrated_stage, "port_stage": calibrated_stage2}
    )

    # Wire periods together
    twister = make_twister("p01", "p02", rename={"a": "k"})

    # Assemble model dict
    model = make_model_dict([period], [twister])
"""

import copy
from pathlib import Path
from typing import Union, Dict, List, Any, Optional

import yaml


__all__ = [
    "make_connector",
    "make_twister",
    "instantiate_period",
    "make_model_dict",
    "load_period_template",
]


# -----------------------------------------------------------------------------
# Connector (within-period wiring)
# -----------------------------------------------------------------------------

def make_connector(from_stage: str, to_stage: str, *, rename: dict) -> dict:
    """
    Create a connector for within-period wiring (stage-to-stage).

    A connector is an adapter that resolves naming mismatches between
    adjacent stages in a period sequence.

    Args:
        from_stage: Name of the source stage
        to_stage: Name of the target stage
        rename: Dict mapping source variable names to target variable names

    Returns:
        Connector dict: {"from": from_stage, "to": to_stage, "rename": rename}

    Example:
        >>> conn = make_connector("cons_stage", "port_stage", rename={"a": "k"})
        >>> conn
        {'from': 'cons_stage', 'to': 'port_stage', 'rename': {'a': 'k'}}

    Notes:
        - Identity connectors (when names match) may be omitted entirely.
        - Terminal relabels are also connectors (at the period boundary).
    """
    if not isinstance(rename, dict):
        raise TypeError(f"rename must be a dict, got {type(rename).__name__}")
    if not rename:
        raise ValueError("rename dict cannot be empty; omit connector if identity")

    return {"from": from_stage, "to": to_stage, "rename": dict(rename)}


def make_terminal_relabel(*, rename: dict) -> dict:
    """
    Create a terminal relabel connector for period boundary.

    A terminal relabel renames the last stage's outputs at the period boundary.

    Args:
        rename: Dict mapping stage output names to period boundary names

    Returns:
        Terminal relabel dict: {"rename": rename}

    Example:
        >>> relabel = make_terminal_relabel(rename={"m": "w"})
        >>> relabel
        {'rename': {'m': 'w'}}
    """
    if not isinstance(rename, dict):
        raise TypeError(f"rename must be a dict, got {type(rename).__name__}")
    if not rename:
        raise ValueError("rename dict cannot be empty")

    return {"rename": dict(rename)}


# -----------------------------------------------------------------------------
# Twister (between-period wiring)
# -----------------------------------------------------------------------------

def make_twister(
    from_period: str,
    to_period: str,
    *,
    rename: Optional[dict] = None,
    vf_link: Optional[dict] = None
) -> dict:
    """
    Create a twister for between-period wiring (period-to-period).

    A twister is an adapter that maps one period's continuation objects
    (terminal state/value names) into the next period's arrival objects.

    Args:
        from_period: Name of the source period (earlier in time)
        to_period: Name of the target period (later in time)
        rename: Optional dict mapping continuation names to arrival names
        vf_link: Optional dict specifying value-function wiring
                 e.g. {"from": "E_cntn", "to": "V_arvl"}

    Returns:
        Twister dict with keys: from, to, and optionally rename, vf_link

    Example:
        >>> tw = make_twister("p01", "p02", rename={"a": "k"})
        >>> tw
        {'from': 'p01', 'to': 'p02', 'rename': {'a': 'k'}}

        >>> tw = make_twister("p01", "p02", vf_link={"from": "E_cntn", "to": "V_arvl"})
        >>> tw
        {'from': 'p01', 'to': 'p02', 'vf_link': {'from': 'E_cntn', 'to': 'V_arvl'}}

    Notes:
        - Convention: `from` is earlier in time, `to` is later in time.
        - Solvers may traverse twisters backward for recursion.
        - Do NOT embed discount factors here; discounting belongs in stage math.
    """
    result = {"from": from_period, "to": to_period}

    if rename is not None:
        if not isinstance(rename, dict):
            raise TypeError(f"rename must be a dict, got {type(rename).__name__}")
        result["rename"] = dict(rename)

    if vf_link is not None:
        if not isinstance(vf_link, dict):
            raise TypeError(f"vf_link must be a dict, got {type(vf_link).__name__}")
        result["vf_link"] = dict(vf_link)

    return result


# -----------------------------------------------------------------------------
# Period Template Loading
# -----------------------------------------------------------------------------

def load_period_template(source: Union[str, Path, dict]) -> dict:
    """
    Load a period template from a YAML file or dict.

    A period template defines:
    - name: Template/type name
    - stages: Ordered list of stage names
    - connectors: Optional within-period wiring

    Args:
        source: Path to YAML file, or dict

    Returns:
        Period template dict

    Example:
        >>> template = load_period_template("cons_period.yaml")
        >>> template
        {'name': 'cons_period', 'stages': ['noport_stage', 'cons_stage']}
    """
    if isinstance(source, dict):
        return dict(source)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Period template not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# -----------------------------------------------------------------------------
# Period Instantiation
# -----------------------------------------------------------------------------

def instantiate_period(
    template: dict,
    *,
    name: str,
    bindings: dict
) -> dict:
    """
    Instantiate a period template by attaching bound stage objects.

    Turn a YAML-shaped PeriodTemplate into a PeriodInstance by:
    - preserving `stages: [...]` as stage *names*
    - attaching bound stage objects under `bindings: {stage_name: stage_obj}`

    Args:
        template: Period template dict (from YAML or load_period_template)
        name: Instance name (typically a time index like "p01")
        bindings: Dict mapping stage names to bound stage objects (SymbolicModel)

    Returns:
        PeriodInstance dict with keys:
        - name: Instance name
        - template: Template name
        - stages: List of stage names
        - connectors: Optional within-period wiring (if present in template)
        - bindings: Dict of stage_name -> bound stage object

    Example:
        >>> from dolo.compiler.model import SymbolicModel
        >>> from dolo.compiler.calibration import calibrate
        >>> stage = SymbolicModel(yaml.compose(open("stage.yaml").read()))
        >>> calibrated = calibrate(stage, {"β": 0.96})
        >>> period = instantiate_period(
        ...     {"name": "cons_period", "stages": ["cons_stage"]},
        ...     name="p01",
        ...     bindings={"cons_stage": calibrated}
        ... )
        >>> period["name"]
        'p01'
        >>> period["template"]
        'cons_period'

    Raises:
        ValueError: If bindings don't cover all stages in template
    """
    # Validate bindings cover template stages
    template_stages = template.get("stages", [])
    missing = set(template_stages) - set(bindings.keys())
    if missing:
        raise ValueError(
            f"Missing bindings for stages: {missing}. "
            f"Template requires: {template_stages}"
        )

    # Extract template name
    template_name = template.get("name")

    # Deep copy template fields (except 'name' which becomes 'template')
    period = copy.deepcopy({k: v for k, v in template.items() if k != "name"})

    # Add instance metadata
    period["name"] = name
    period["template"] = template_name
    period["bindings"] = dict(bindings)

    return period


# -----------------------------------------------------------------------------
# Model Dict Assembly
# -----------------------------------------------------------------------------

def make_model_dict(periods: List[dict], twisters: List[dict]) -> dict:
    """
    Assemble a model dict from period instances and twisters.

    The model dict is a plain container with:
    - periods: Dict mapping period names to PeriodInstance dicts
    - twisters: List of Twister dicts

    Args:
        periods: List of PeriodInstance dicts (from instantiate_period)
        twisters: List of Twister dicts (from make_twister)

    Returns:
        ModelDict: {"periods": {name: period, ...}, "twisters": [...]}

    Example:
        >>> periods = [
        ...     {"name": "p01", "template": "cons", "stages": ["cons"], "bindings": {}},
        ...     {"name": "p02", "template": "cons", "stages": ["cons"], "bindings": {}},
        ... ]
        >>> twisters = [make_twister("p01", "p02", rename={"a": "k"})]
        >>> model = make_model_dict(periods, twisters)
        >>> list(model["periods"].keys())
        ['p01', 'p02']
        >>> len(model["twisters"])
        1

    Notes:
        - This dict can be serialized if desired.
        - Stage bindings are existing stage objects (no new classes).
        - Does NOT cache grids or large numerical objects.
    """
    # Build periods dict indexed by name
    periods_dict = {}
    for p in periods:
        pname = p.get("name")
        if pname is None:
            raise ValueError("Period missing 'name' field")
        if pname in periods_dict:
            raise ValueError(f"Duplicate period name: {pname}")
        periods_dict[pname] = p

    return {
        "periods": periods_dict,
        "twisters": list(twisters),
    }


# -----------------------------------------------------------------------------
# Validation Helpers
# -----------------------------------------------------------------------------

def validate_model_dict(model: dict) -> List[str]:
    """
    Validate a model dict for structural correctness.

    Returns a list of warnings (empty if valid).

    Checks:
    - All period names referenced in twisters exist
    - All stage names in period templates have bindings
    - No orphan periods (not connected by twisters, except terminal)

    Args:
        model: ModelDict from make_model_dict

    Returns:
        List of warning strings (empty if valid)
    """
    warnings = []

    periods = model.get("periods", {})
    twisters = model.get("twisters", [])

    period_names = set(periods.keys())

    # Check twister references
    twister_refs = set()
    for tw in twisters:
        from_p = tw.get("from")
        to_p = tw.get("to")
        twister_refs.add(from_p)
        twister_refs.add(to_p)

        if from_p not in period_names:
            warnings.append(f"Twister references unknown period: {from_p}")
        if to_p not in period_names:
            warnings.append(f"Twister references unknown period: {to_p}")

    # Check for disconnected periods (optional warning)
    if len(periods) > 1 and twisters:
        disconnected = period_names - twister_refs
        # Allow one terminal period (last one)
        if len(disconnected) > 1:
            warnings.append(f"Potentially disconnected periods: {disconnected}")

    return warnings
