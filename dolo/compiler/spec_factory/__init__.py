"""Spec factory — recipe-based specification resolution (spec 0.1s).

Core API:
    load(path) -> Recipe (unresolved source names + slot positions)
    make(recipe, registry_dir, **slots) -> SpecGraph (immutable resolved dicts)

Utilities:
    override_methods — structured method patching at (stage, target, scheme) level
    parse_method_override_str — CLI string parser for method overrides
"""

from .loader import load, Recipe, StageRecipe, SpecFactoryError
from .maker import make
from .graph import SpecGraph
from .method_overrides import override_methods, parse_method_override_str

__all__ = [
    "load",
    "make",
    "Recipe",
    "StageRecipe",
    "SpecGraph",
    "SpecFactoryError",
    "override_methods",
    "parse_method_override_str",
]
