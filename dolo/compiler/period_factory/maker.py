"""Period assembly: build one period from stage sources.

Supports two calling conventions:
- 0.1s (SpecGraph): make(spec, h, period_template, sym_stages, upto=...)
- 0.1r (flat dicts): make(calibration, settings, stage_sources, period_template, upto=...)

Detection: if first arg has .stage_names attribute → 0.1s path.
"""

from __future__ import annotations


def _make_stage_from_src(name, src, methods, calibration, settings, upto="specified"):
    """Apply stage_factory verbs to one stage (0.1r path)."""
    from dolo.compiler.stage_factory import (sym, methodize, configure, calibrate)

    s = sym({"yaml_text": src["yaml_text"], "yaml_path": src["yaml_path"]})
    if upto == "symbolic":
        return s
    s = methodize(s, methods)
    if upto == "methodized":
        return s
    s = configure(s, settings)
    if upto == "configured":
        return s
    s = calibrate(s, calibration)
    return s


def _make_stage_from_spec(stage_name, sym_stage_src, spec, h, upto="specified"):
    """Apply stage_factory verbs using SpecGraph lookups (0.1s path)."""
    from dolo.compiler.stage_factory import (sym, methodize, configure, calibrate)

    s = sym(sym_stage_src)
    if upto == "symbolic":
        return s
    s = methodize(s, spec[stage_name][h]["methods"])
    if upto == "methodized":
        return s
    s = configure(s, spec[stage_name][h]["settings"])
    if upto == "configured":
        return s
    s = calibrate(s, spec[stage_name][h]["calibration"])
    return s


def make(first, second=None, third=None, fourth=None, upto="specified"):
    """Build one period by applying the dolo-plus pipeline to each stage.

    Two calling conventions:

    **0.1s (SpecGraph)**::

        make(spec, h, period_template, sym_stages, upto="specified")

    **0.1r (flat dicts)**::

        make(calibration, settings, stage_sources, period_template, upto="specified")

    Detection: if ``first`` has a ``stage_names`` attribute, use the
    0.1s path. Otherwise, use the 0.1r path.

    Parameters (0.1s path)
    ----------------------
    spec : SpecGraph
        From spec_factory.make(). Provides per-stage per-period lookups.
    h : int
        Period index.
    period_template : dict
        {"stages": [name, ...], "connectors": [...]}.
    sym_stages : dict
        {stage_name: {"yaml_text": str, "yaml_path": str}} — raw stage sources.
    upto : str
        Pipeline level: "symbolic", "methodized", "configured", "specified".

    Parameters (0.1r path)
    ----------------------
    calibration : dict
    settings : dict
    stage_sources : dict
    period_template : dict
    upto : str

    Returns
    -------
    dict
        {"stages": {name: SymbolicModel, ...}, "connectors": [...]}.
    """
    if hasattr(first, 'stage_names'):
        return _make_from_spec(first, second, third, fourth, upto=upto)
    else:
        return _make_from_flat(first, second, third, fourth, upto=upto)


def _make_from_spec(spec, h, period_template, sym_stages, upto="specified"):
    """0.1s path: build period from SpecGraph."""
    stages = {}
    for stage_name in period_template["stages"]:
        if not spec.is_active(stage_name, h):
            continue
        stages[stage_name] = _make_stage_from_spec(
            stage_name,
            sym_stages[stage_name],
            spec, h,
            upto=upto,
        )
    return {
        "stages": stages,
        "connectors": period_template.get("connectors", []),
    }


def _make_from_flat(calibration, settings, stage_sources, period_template, upto="specified"):
    """0.1r path: build period from flat dicts."""
    stages = {}
    for name in period_template["stages"]:
        src = stage_sources[name]
        stages[name] = _make_stage_from_src(
            name,
            src={"yaml_text": src["yaml_text"], "yaml_path": src["yaml_path"]},
            methods=src["methods"],
            calibration=calibration,
            settings=settings,
            upto=upto,
        )
    return {
        "stages": stages,
        "connectors": period_template.get("connectors", []),
    }
