"""YAML loading that tolerates unknown tags (!stage, !period, …).

Shared by ``period_factory.load`` and ``stage_factory.load_syntax`` (spec 0.1r).
"""

from __future__ import annotations

import yaml
from pathlib import Path


class TagTolerantSafeLoader(yaml.SafeLoader):
    """SafeLoader that ignores unknown YAML tags instead of crashing."""

    pass


def _strip_unknown_tag(loader, suffix, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    return loader.construct_sequence(node)


TagTolerantSafeLoader.add_multi_constructor("", _strip_unknown_tag)


def load_yaml_tag_tolerant(path):
    """Load a YAML file, stripping unknown tags to plain Python objects."""
    path = Path(path)
    with open(path) as f:
        return yaml.load(f, Loader=TagTolerantSafeLoader)
