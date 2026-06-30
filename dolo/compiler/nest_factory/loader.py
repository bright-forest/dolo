"""Nest loading from syntax directory.

Migrated from kikku/dynx/connectors.py (spec 0.1r).
"""

from __future__ import annotations
from pathlib import Path
import yaml


def load(syntax_dir):
    """Load nest configuration from a syntax directory."""
    path = Path(syntax_dir) / "nest.yaml"

    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_multi_constructor(
        "",
        lambda loader, suffix, node: (
            loader.construct_mapping(node)
            if isinstance(node, yaml.MappingNode)
            else None
        ),
    )

    with open(path) as f:
        nest_yaml = yaml.load(f, Loader=_Loader)

    connectors = nest_yaml.get("inter_connectors", [])
    inter_conn = connectors[0] if connectors else {}

    return {
        "nest_yaml": nest_yaml,
        "inter_conn": inter_conn,
    }


def load_inter_connector(syntax_dir):
    """Load the inter-period connector from nest.yaml. Backward compat wrapper."""
    result = load(syntax_dir)
    return result["inter_conn"]
