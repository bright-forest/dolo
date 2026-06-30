"""Immutable spec graph (spec 0.1s).

The SpecGraph is the resolved output of spec_factory.make().
It provides lookups by spec[stage_name][period_index]["dimension"].
All returned dicts are immutable (MappingProxyType — shallow freeze).
"""

from __future__ import annotations

import copy
import re
import types
from typing import Any


_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")


def _freeze(obj):
    """Recursively freeze dicts/lists into immutable structures."""
    if isinstance(obj, types.MappingProxyType):
        return obj
    if isinstance(obj, dict):
        return types.MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(item) for item in obj)
    return obj


class _StageView:
    """Lookup by period index for a single stage."""

    def __init__(self, stage_name, dim_data, periods):
        self._stage_name = stage_name
        self._dim_data = dim_data
        self._periods = periods

    def __getitem__(self, h):
        if self._periods is not None:
            lo, hi = self._periods
            if h < lo or h > hi:
                raise KeyError(
                    f"Stage '{self._stage_name}' is not active at period {h} "
                    f"(active range: [{lo}, {hi}])"
                )
        return _PeriodView(self._stage_name, h, self._dim_data)

    def is_active(self, h):
        if self._periods is None:
            return True
        lo, hi = self._periods
        return lo <= h <= hi

    def __repr__(self):
        return f"_StageView({self._stage_name!r}, dims={list(self._dim_data.keys())})"


class _PeriodView:
    """Lookup by dimension for a (stage, period) pair."""

    def __init__(self, stage_name, h, dim_data):
        self._stage_name = stage_name
        self._h = h
        self._dim_data = dim_data

    def __getitem__(self, dim_name):
        if dim_name not in self._dim_data:
            raise KeyError(
                f"Unknown dimension '{dim_name}' for stage '{self._stage_name}'. "
                f"Valid: {list(self._dim_data.keys())}"
            )
        groups = self._dim_data[dim_name]

        for key, resolved in groups.items():
            if key == "all":
                continue
            m = _RANGE_RE.match(key)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                if lo <= self._h <= hi:
                    return _freeze(resolved)

        return _freeze(groups.get("all", {}))

    def __repr__(self):
        return f"_PeriodView({self._stage_name!r}, h={self._h})"


class SpecGraph:
    """Immutable spec graph — resolved output of spec_factory.make().

    Access pattern:
        spec[stage_name][h]["calibration"] -> MappingProxyType
        spec[stage_name][h]["settings"]    -> MappingProxyType
        spec[stage_name][h]["methods"]     -> MappingProxyType

    The graph is immutable after construction (shallow freeze).
    """

    def __init__(self, stage_data):
        self._stages = {}
        for stage_name, data in stage_data.items():
            data = dict(data)
            periods = data.pop("periods", None)
            self._stages[stage_name] = _StageView(
                stage_name, data, periods
            )

    def __getitem__(self, stage_name):
        if stage_name not in self._stages:
            available = sorted(self._stages.keys())
            raise KeyError(
                f"Stage '{stage_name}' not in spec graph. "
                f"Available: {available}"
            )
        return self._stages[stage_name]

    def __contains__(self, stage_name):
        return stage_name in self._stages

    def is_active(self, stage_name, h):
        if stage_name not in self._stages:
            return False
        return self._stages[stage_name].is_active(h)

    @property
    def stage_names(self):
        return list(self._stages.keys())

    def __repr__(self):
        return f"SpecGraph(stages={self.stage_names})"
