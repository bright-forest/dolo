"""Spec factory recipe loader (spec 0.1s).

Reads a spec_factory YAML file and returns an unresolved Recipe.
The recipe contains source names and slot positions but NO loaded
file contents. File loading happens in make().
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml


class SpecFactoryError(Exception):
    """Raised for validation errors in spec_factory YAML."""
    pass


class StageRecipe:
    """Per-stage recipe: source lists per dimension per period-group."""

    def __init__(self, name, calibration, settings, methods, periods=None):
        self.name = name
        self.calibration = calibration  # {"all": ["calibration/main", "$draw"], "45-59": [...]}
        self.settings = settings        # same structure
        self.methods = methods           # same structure
        self.periods = periods           # (lo, hi) or None = whole horizon

    def __repr__(self):
        return f"StageRecipe({self.name!r})"


class Recipe:
    """Unresolved spec_factory recipe.

    Contains source names and slot positions. No files are loaded.

    Access:
        recipe.stages -> dict of StageRecipe
        recipe.slots -> set of slot names (without $ prefix)
        recipe[stage_name] -> StageRecipe
    """

    def __init__(self, stages, slots, path=None):
        self.stages = stages    # {name: StageRecipe}
        self.slots = slots      # {"draw", "method_switch"}
        self.path = path        # path to the YAML file

    def __getitem__(self, stage_name):
        return self.stages[stage_name]

    def __contains__(self, stage_name):
        return stage_name in self.stages

    def __repr__(self):
        return f"Recipe(stages={list(self.stages.keys())}, slots={self.slots})"

    def list_sources(self, dimension=None):
        """List all unique source names (not slots)."""
        sources = set()
        for sr in self.stages.values():
            for dim_name in (["calibration", "settings", "methods"] if dimension is None else [dimension]):
                dim_data = getattr(sr, dim_name, {})
                for group_sources in dim_data.values():
                    for s in group_sources:
                        if not s.startswith("$"):
                            sources.add(s)
        return sorted(sources)

    def list_slots(self):
        """List all declared slot names."""
        return sorted(self.slots)


_RANGE_PATTERN = re.compile(r"^(\d+)-(\d+)$")
_DIMENSIONS = ("calibration", "settings", "methods")


def _parse_range(key):
    """Parse "lo-hi" string to (lo, hi) integers."""
    m = _RANGE_PATTERN.match(key)
    if not m:
        raise SpecFactoryError(
            f"Invalid period range key: '{key}'\n"
            f"  x Expected format: 'lo-hi' (e.g., '45-59')\n"
            f"  i Period ranges must be non-negative integer pairs."
        )
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        raise SpecFactoryError(
            f"Invalid period range: '{key}'\n"
            f"  x lo ({lo}) must be <= hi ({hi})."
        )
    return (lo, hi)


def _validate_no_overlap(ranges, stage_name, dim_name):
    """Check that explicit ranges (not 'all') don't overlap."""
    sorted_ranges = sorted(ranges)
    for i in range(len(sorted_ranges) - 1):
        a_lo, a_hi = sorted_ranges[i]
        b_lo, b_hi = sorted_ranges[i + 1]
        if a_hi >= b_lo:
            raise SpecFactoryError(
                f"Overlapping period ranges in {stage_name}.{dim_name}\n"
                f"  x Range '{a_lo}-{a_hi}' overlaps with '{b_lo}-{b_hi}'.\n"
                f"  i Period ranges for each (stage, dimension) must be non-overlapping."
            )


def _validate_source_name(name, stage_name, dim_name, group_key):
    """Validate a source name (not a slot)."""
    if ".." in name:
        raise SpecFactoryError(
            f"Invalid source name '{name}' in {stage_name}.{dim_name}.{group_key}\n"
            f"  x Source names must not contain '..'.\n"
            f"  i Use relative paths from the registry root."
        )
    if Path(name).is_absolute():
        raise SpecFactoryError(
            f"Invalid source name '{name}' in {stage_name}.{dim_name}.{group_key}\n"
            f"  x Source names must be relative paths, not absolute.\n"
            f"  i Use paths relative to the registry root."
        )


def _parse_dimension(dim_data, stage_name, dim_name):
    """Parse one dimension block into {group_key: [source_list]} and collect slots."""
    if dim_data is None:
        return {"all": []}, set()

    if not isinstance(dim_data, dict):
        raise SpecFactoryError(
            f"Invalid {dim_name} block in stage '{stage_name}'\n"
            f"  x Expected a mapping with 'all' key, got {type(dim_data).__name__}."
        )

    if "all" not in dim_data:
        raise SpecFactoryError(
            f"Missing 'all' key in {stage_name}.{dim_name}\n"
            f"  x Every dimension must have an 'all' source list.\n"
            f"  i The 'all' list applies to every period."
        )

    result = {}
    slots = set()
    explicit_ranges = []

    for key, source_list in dim_data.items():
        if source_list is None:
            source_list = []
        if not isinstance(source_list, list):
            source_list = [source_list]

        sources = []
        for s in source_list:
            s = str(s).strip()
            if s.startswith("$"):
                slot_name = s[1:]
                slots.add(slot_name)
                sources.append(s)
            else:
                _validate_source_name(s, stage_name, dim_name, key)
                sources.append(s)

        if key == "all":
            result["all"] = sources
        else:
            rng = _parse_range(key)
            explicit_ranges.append(rng)
            result[key] = sources

    _validate_no_overlap(explicit_ranges, stage_name, dim_name)
    return result, slots


def load(path):
    """Read a spec_factory YAML and return an unresolved Recipe.

    The recipe contains source names and slot positions but NO
    loaded file contents. File loading happens in make().

    Parameters
    ----------
    path : str or Path
        Path to the spec_factory YAML file.

    Returns
    -------
    Recipe
        Inspectable object with .stages, .slots, and [] access.

    Raises
    ------
    SpecFactoryError
        If period ranges overlap, source names are malformed, or
        required structure is missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Spec factory file not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)

    if raw is None or "stages" not in raw:
        raise SpecFactoryError(
            f"Invalid spec_factory YAML: {path}\n"
            f"  x Missing top-level 'stages' key.\n"
            f"  i A spec_factory YAML must have: stages: <stage_name>: calibration/settings/methods: ..."
        )

    stages_raw = raw["stages"]
    if not isinstance(stages_raw, dict):
        raise SpecFactoryError(
            f"Invalid spec_factory YAML: {path}\n"
            f"  x 'stages' must be a mapping, got {type(stages_raw).__name__}."
        )

    all_slots = set()
    stages = {}

    for stage_name, stage_data in stages_raw.items():
        if not isinstance(stage_data, dict):
            raise SpecFactoryError(
                f"Invalid stage '{stage_name}' in {path}\n"
                f"  x Stage data must be a mapping with calibration/settings/methods keys."
            )

        periods = None
        if "periods" in stage_data:
            p = stage_data["periods"]
            if isinstance(p, list) and len(p) == 2:
                periods = (int(p[0]), int(p[1]))
            else:
                raise SpecFactoryError(
                    f"Invalid 'periods' in stage '{stage_name}'\n"
                    f"  x Expected [lo, hi], got {p}."
                )

        dim_data = {}
        for dim in _DIMENSIONS:
            parsed, slots = _parse_dimension(
                stage_data.get(dim), stage_name, dim
            )
            dim_data[dim] = parsed
            all_slots.update(slots)

        stages[stage_name] = StageRecipe(
            name=stage_name,
            calibration=dim_data["calibration"],
            settings=dim_data["settings"],
            methods=dim_data["methods"],
            periods=periods,
        )

    return Recipe(stages=stages, slots=all_slots, path=str(path))
