"""Spec factory (spec 0.1s — core load/make/SpecGraph are stubs).

``override_methods`` and ``parse_method_override_str`` are real functions
moved here from kikku/dynx/methods.py in 0.1r. They are utilities
used by solve pipelines for method comparison (FUES vs NEGM).
The core spec_factory functionality (recipe YAML, source
composition, slots, SpecGraph) is deferred to spec 0.1s.
"""

from .loader import load
from .maker import make
from .graph import SpecGraph
from .method_overrides import override_methods, parse_method_override_str

__all__ = [
    "load",
    "make",
    "SpecGraph",
    "override_methods",
    "parse_method_override_str",
]
