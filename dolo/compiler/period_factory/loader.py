"""Period template loader (spec 0.1r)."""

from pathlib import Path

from dolo.compiler.tag_tolerant_yaml import load_yaml_tag_tolerant


def load(path):
    """Load a period template YAML (stage list + wiring).

    Tolerates unknown YAML tags (!stage, !period, etc.) by
    stripping them and returning the underlying data.
    """
    path = Path(path)
    raw = load_yaml_tag_tolerant(path)
    stage_names = []
    for entry in raw.get("stages", []):
        if isinstance(entry, dict):
            stage_names.extend(entry.keys())
        else:
            stage_names.append(str(entry))
    return {
        "name": raw.get("name", path.stem),
        "stages": stage_names,
        "connectors": raw.get("connectors", []),
    }
