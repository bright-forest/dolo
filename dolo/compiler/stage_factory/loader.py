"""Stage loading — the I/O boundary.

Migrated from kikku/dynx/io.py (spec 0.1r).
"""

from __future__ import annotations

import yaml
from pathlib import Path

from dolo.compiler.tag_tolerant_yaml import load_yaml_tag_tolerant


def load(path):
    """Load a stage YAML file and return raw dict."""
    path = Path(path)
    with open(path) as f:
        yaml_text = f.read()
    return {"yaml_text": yaml_text, "yaml_path": str(path)}


def load_syntax(syntax_dir, calib_overrides=None,
                config_overrides=None):
    """Load all YAML inputs from a dolo-plus syntax directory.

    Migrated from kikku/dynx/io.py (spec 0.1r).

    Parameters
    ----------
    syntax_dir : str or Path
        Root syntax directory.
    calib_overrides, config_overrides : dict, optional
        Sparse overrides applied after loading.

    Returns
    -------
    calibration : dict
    settings : dict
    stage_sources : dict
    period_template : dict
    inter_conn : dict
    """
    from dolo.compiler.methodization import load_methodization

    syntax_dir = Path(syntax_dir)

    with open(syntax_dir / "calibration.yaml") as f:
        calibration = yaml.safe_load(f)['calibration']
    if calib_overrides:
        calibration.update(calib_overrides)

    with open(syntax_dir / "settings.yaml") as f:
        settings = yaml.safe_load(f)['settings']
    if config_overrides:
        settings.update(config_overrides)

    raw = load_yaml_tag_tolerant(syntax_dir / "period.yaml")
    stage_names = []
    for entry in raw.get('stages', []):
        if isinstance(entry, dict):
            stage_names.extend(entry.keys())
        else:
            stage_names.append(str(entry))

    stages_dir = syntax_dir / "stages"
    stage_sources = {}
    for name in stage_names:
        stage_yaml_path = stages_dir / name / f"{name}.yaml"
        with open(stage_yaml_path) as f:
            yaml_text = f.read()
        methods_path = stages_dir / name / f"{name}_methods.yml"
        methods_dict = load_methodization(methods_path)
        stage_sources[name] = {
            "yaml_text": yaml_text,
            "yaml_path": str(stage_yaml_path),
            "methods": methods_dict,
        }

    period_template = {
        "name": raw["name"],
        "stages": stage_names,
        "connectors": raw.get("connectors", []),
    }

    from dolo.compiler.nest_factory.loader import load_inter_connector
    inter_conn = load_inter_connector(syntax_dir)

    return calibration, settings, stage_sources, \
        period_template, inter_conn
