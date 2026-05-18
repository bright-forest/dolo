"""Method override utilities for DDSL stage sources.

Operates on raw stage_sources (before period instantiation).
Model-agnostic: knows about the methods YAML structure
({on: target, schemes: [{scheme: name, method: tag}]})
but not about specific scheme names or method values.
"""

import copy


def override_methods(stage_sources, method_overrides):
    """Patch method tags in stage_sources before instantiation.

    Parameters
    ----------
    stage_sources : dict
        From ``load_syntax()``. Keys are stage names, values have
        ``["methods"]["methods"]`` list of ``{on: target, schemes: [...]}``.
    method_overrides : dict
        ``{(stage_name, target, scheme_name): method_tag, ...}``
        e.g. ``{('adjuster_cons', 'cntn_to_dcsn_builder', 'upper_envelope'): 'NEGM'}``

    Returns
    -------
    dict
        Deep copy of stage_sources with method tags patched.

    Raises
    ------
    ValueError
        If a (stage, target, scheme) triple does not exist in stage_sources.
    """
    patched = copy.deepcopy(stage_sources)
    for (stage_name, target, scheme_name), tag in method_overrides.items():
        src = patched.get(stage_name)
        if src is None:
            raise ValueError(
                f"Method override: stage '{stage_name}' not in stage_sources. "
                f"Available: {list(patched.keys())}")
        methods_list = src.get("methods", {}).get("methods", [])
        found = False
        for entry in methods_list:
            if entry.get("on") != target:
                continue
            for scheme in entry.get("schemes", []):
                if scheme.get("scheme") == scheme_name:
                    scheme["method"] = {
                        "__yaml_tag__": tag.upper(), "value": ""}
                    found = True
        if not found:
            raise ValueError(
                f"Method override: scheme '{scheme_name}' on target "
                f"'{target}' not found in stage '{stage_name}'")
    return patched


def parse_method_override_str(raw):
    """Parse CLI string 'stage.target.scheme=TAG' into key + value.

    Also supports shorthand 'stage.scheme=TAG' (target defaults to
    'cntn_to_dcsn_builder').

    Returns
    -------
    (stage, target, scheme), tag
    """
    if '=' not in raw:
        raise ValueError(
            f"Method override must be path=TAG, got: {raw}")
    path, tag = raw.rsplit('=', 1)
    parts = path.split('.')
    if len(parts) == 3:
        stage, target, scheme = parts
    elif len(parts) == 2:
        stage, scheme = parts
        target = 'cntn_to_dcsn_builder'  # default target
    else:
        raise ValueError(
            f"Method override path must be stage.target.scheme or "
            f"stage.scheme, got: {path}")
    return (stage, target, scheme), tag.strip()
