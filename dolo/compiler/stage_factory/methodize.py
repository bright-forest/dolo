"""Methodization functor — attaches numerical method schemes to a stage (spec_0.1d)."""

import copy
from pathlib import Path
from typing import Union, Optional, List


def methodize(stage, methodization_source: Union[str, Path, dict],
              registry: Optional[dict] = None,
              strict: bool = False):
    """
    Apply methodization functor to a stage (spec_0.1d).

    Returns a NEW stage object with `.methods` attached.
    The original stage is not mutated.

    The methodization is expanded to be exhaustive over all targets:
    - Stage labels (equations, movers)
    - Sub-equation labels (dot notation)
    - Operator instances (E_y, etc.)

    Missing targets are filled with `schemes: []`.

    Args:
        stage: SymbolicModel (syntactic stage)
        methodization_source: Path to methodization.yml, or dict
        registry: Optional operation registry for scheme validation
        strict: If True, raise on unknown targets; if False, warn

    Returns:
        New SymbolicModel with `.methods` attached

    Example:
        >>> methodized = methodize(stage, "methodization.yml")
        >>> methodized.methods['E_y']
        {'on': 'E_y', 'schemes': [{'scheme': 'expectation', ...}]}
    """
    from dolo.compiler.methodization import (
        load_methodization, extract_stage_targets, extract_operator_instances,
    )

    config = load_methodization(methodization_source)
    provided_methods = config.get('methods', [])

    stage_targets = extract_stage_targets(stage)
    operator_targets = extract_operator_instances(stage)
    all_targets = stage_targets + operator_targets

    provided_map = {}
    for entry in provided_methods:
        target = entry.get('on')
        if target in provided_map:
            raise ValueError(f"Duplicate methodization target: {target}")
        provided_map[target] = entry

    for target in provided_map:
        if target not in all_targets:
            msg = f"Unknown methodization target: {target}"
            if strict:
                raise ValueError(msg)
            else:
                import warnings
                warnings.warn(msg)

    expanded_methods = []
    for target in all_targets:
        if target in provided_map:
            expanded_methods.append(provided_map[target])
        else:
            expanded_methods.append({'on': target, 'schemes': []})

    if registry:
        _validate_schemes(expanded_methods, registry)

    _validate_settings_symbols(expanded_methods, stage)

    new_stage = copy.copy(stage)
    new_stage._methods = {entry['on']: entry for entry in expanded_methods}
    new_stage._methods_list = expanded_methods

    return new_stage


def _validate_schemes(methods: List[dict], registry: dict):
    """Warn on unknown scheme names."""
    import warnings

    registered_schemes = set(registry.get('schemes', {}).keys())

    for entry in methods:
        for scheme_block in entry.get('schemes', []):
            scheme_name = scheme_block.get('scheme')
            if scheme_name and scheme_name not in registered_schemes:
                warnings.warn(f"Unknown scheme '{scheme_name}' for target '{entry['on']}'")


def _validate_settings_symbols(methods: List[dict], stage):
    """Warn if settings symbols are not declared in stage."""
    import warnings

    declared_settings = set()
    if hasattr(stage, 'symbols') and 'settings' in stage.symbols:
        declared_settings = set(stage.symbols['settings'])

    def extract_symbol_names(value):
        if isinstance(value, str):
            return [value]
        elif isinstance(value, list):
            names = []
            for item in value:
                names.extend(extract_symbol_names(item))
            return names
        return []

    for entry in methods:
        for scheme_block in entry.get('schemes', []):
            settings = scheme_block.get('settings', {})
            for option_key, symbol_value in settings.items():
                for symbol_name in extract_symbol_names(symbol_value):
                    if symbol_name not in declared_settings:
                        warnings.warn(
                            f"Settings symbol '{symbol_name}' (for {entry['on']}.{option_key}) "
                            f"not declared in stage symbols.settings"
                        )
