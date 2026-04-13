"""Period assembly: build one period from stage sources.

Migrated from kikku/dynx/stage_maker.py and kikku/dynx/period_maker.py (spec 0.1r).
"""

from __future__ import annotations


def _make_stage(name, src, methods, calibration, settings, upto="specified"):
    """Apply stage_factory verbs to one stage, stopping at ``upto``."""
    from dolo.compiler.stage_factory import (
        sym,
        methodize,
        configure,
        calibrate,
    )

    s = sym(
        {
            "yaml_text": src["yaml_text"],
            "yaml_path": src["yaml_path"],
        }
    )
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


def make(calibration, settings, stage_sources, period_template, upto="specified"):
    """Build one period by applying the dolo-plus pipeline to each stage.

    Parameters
    ----------
    calibration : dict
        Economic parameters (consumed by ``calibrate``).
    settings : dict
        Numerical/structural settings (consumed by ``configure``).
    stage_sources : dict
        Pre-loaded stage data per stage name::

            {name: {"yaml_text": str, "yaml_path": str,
                     "methods": dict}, ...}

    period_template : dict
        ``{"stages": [name, ...], "connectors": [...]}``.
    upto : str, optional
        Stop pipeline early ("symbolic", "methodized", "configured",
        "specified"). Default is full chain.

    Returns
    -------
    dict
        Canonical period dict: ``{"stages": {...}, "connectors": [...]}``.
    """
    stages = {}
    for name in period_template["stages"]:
        src = stage_sources[name]
        stages[name] = _make_stage(
            name,
            src={"yaml_text": src["yaml_text"],
                 "yaml_path": src["yaml_path"]},
            methods=src["methods"],
            calibration=calibration,
            settings=settings,
            upto=upto,
        )

    return {
        "stages": stages,
        "connectors": period_template.get("connectors", []),
    }
