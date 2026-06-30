"""dolo: YAML model specification and solution for dynamic economics.

Lazy imports: heavy submodules (algos, numeric, compiler.model_import)
are imported on first access, not at package init. This avoids pulling in
sympy, guvectorize, and 400+ modules when only dolo.compiler.calibration
is needed (the common case for FUES/kikku estimation).
"""

# Always available (lightweight):
from dolo.config import *

# Lazy accessors — imported on first use:
def yaml_import(*args, **kwargs):
    from dolo.compiler.model_import import yaml_import as _yi
    return _yi(*args, **kwargs)

def pcat(*args, **kwargs):
    from dolo.misc.display import pcat as _p
    return _p(*args, **kwargs)

def groot(*args, **kwargs):
    from dolo.misc.groot import groot as _g
    return _g(*args, **kwargs)

def dprint(*args, **kwargs):
    from dolo.misc.dprint import dprint as _d
    return _d(*args, **kwargs)
