"""
Methodization Functor (spec_0.1d)

Attaches numerical-method metadata to a syntactic stage without:
- embedding numbers in the stage file
- changing the math/function bodies
- inventing synthetic target labels

The methodization functor:
    M : (S, OperationRegistry, MethodConfig) → S_method

Usage:
    from dolo.compiler.methodization import methodize, load_methodization

    # Load and attach methods (functorial - returns new stage)
    methodized = methodize(stage, "methodization.yml")

    # Access attached methods
    methodized.methods  # {'E_y': {...}, 'cntn_to_dcsn_mover': {...}, ...}

Targets can be:
- Equation/mover labels (top-level keys under `equations:`)
- Sub-equation labels via dot notation (`cntn_to_dcsn_mover.InvEuler`)
- Operator instance IDs extracted from equation bodies (`E_y`, `E_w`)
"""

import re
import copy
from pathlib import Path
from typing import Union, Dict, List, Any, Optional, Tuple, Set

import yaml


__all__ = [
    "load_methodization",
    "methodize",
    "extract_stage_targets",
    "extract_operator_instances",
    "emit_methodization_template",
]


# -----------------------------------------------------------------------------
# Target Extraction
# -----------------------------------------------------------------------------

def extract_stage_targets(stage) -> List[str]:
    """
    Extract all targetable labels from a stage.

    Returns equation labels and sub-equation labels (dot notation).
    Forward movers are implied from transitions.

    Args:
        stage: SymbolicModel with parsed YAML

    Returns:
        List of target strings, e.g.:
        ['arvl_to_dcsn_transition', 'cntn_to_dcsn_mover',
         'cntn_to_dcsn_mover.Bellman', 'cntn_to_dcsn_mover.InvEuler', ...]
    """
    targets = []

    # Get equations block from stage
    equations = _get_equations_block(stage)
    if not equations:
        return targets

    for label, value in equations.items():
        # Add top-level label
        targets.append(label)

        # If value is a mapping, add sub-labels with dot notation
        if isinstance(value, dict):
            for sublabel in value.keys():
                targets.append(f"{label}.{sublabel}")

    # Add implied forward movers from transitions
    # arvl_to_dcsn_transition → arvl_to_dcsn_mover (forward)
    # dcsn_to_cntn_transition → dcsn_to_cntn_mover (forward)
    for label in list(targets):
        if label.endswith('_transition'):
            forward_mover = label.replace('_transition', '_mover')
            if forward_mover not in targets:
                targets.append(forward_mover)

    return targets


def extract_operator_instances(stage) -> List[str]:
    """
    Extract operator instance IDs from equation bodies.

    Finds expectation operators like E_{y}(...) → 'E_y'
    Multiple subscripts: E_{w,z}(...) → 'E_w_z'

    Args:
        stage: SymbolicModel with parsed YAML

    Returns:
        List of operator instance IDs, e.g.: ['E_y', 'E_w']
    """
    operators = set()

    # Pattern for E_{subscript}( - captures the subscript
    # Handles: E_{y}, E_{w}, E_{w,z}, E_{ε}
    expectation_pattern = re.compile(r'E_\{([^}]+)\}\s*\(')

    equations = _get_equations_block(stage)
    if not equations:
        return list(operators)

    def extract_from_text(text: str):
        """Extract operator instances from equation text."""
        for match in expectation_pattern.finditer(text):
            subscript = match.group(1)
            # Replace commas with underscores for multi-subscript
            op_id = 'E_' + subscript.replace(',', '_').replace(' ', '')
            operators.add(op_id)

    def walk_equations(obj):
        """Recursively walk equation structure."""
        if isinstance(obj, str):
            extract_from_text(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk_equations(v)
        elif isinstance(obj, list):
            for item in obj:
                walk_equations(item)

    walk_equations(equations)

    return sorted(operators)


def _get_equations_block(stage) -> Optional[Dict]:
    """Get equations block from stage, handling both SymbolicModel and raw dict."""
    if hasattr(stage, 'data'):
        # SymbolicModel stores raw YAML in .data (MappingNode)
        from dolang.yaml_nodes import mapping_get, mapping_items
        import yaml.nodes

        data = stage.data
        if isinstance(data, yaml.nodes.MappingNode):
            eqs_node = mapping_get(data, 'equations')
            if eqs_node is None:
                return {}
            # Convert MappingNode to dict
            result = {}
            for key_node, val_node in eqs_node.value:
                key = key_node.value
                if isinstance(val_node, yaml.nodes.ScalarNode):
                    result[key] = val_node.value
                elif isinstance(val_node, yaml.nodes.MappingNode):
                    # Sub-equations
                    result[key] = {}
                    for subkey_node, subval_node in val_node.value:
                        subkey = subkey_node.value
                        if isinstance(subval_node, yaml.nodes.ScalarNode):
                            result[key][subkey] = subval_node.value
                        else:
                            result[key][subkey] = str(subval_node)
            return result
        return data.get('equations', {})
    elif isinstance(stage, dict):
        return stage.get('equations', {})
    return None


# -----------------------------------------------------------------------------
# Methodization Loading
# -----------------------------------------------------------------------------

def load_methodization(source: Union[str, Path, dict]) -> dict:
    """
    Load methodization config from file or dict.

    Handles YAML tags (like !gauss-hermite) by preserving them as strings.
    Also handles 'on' key which YAML interprets as True.

    Args:
        source: Path to methodization YAML, or dict

    Returns:
        Dict with 'stage' (optional) and 'methods' keys

    Example:
        >>> config = load_methodization("methodization.yml")
        >>> config['methods']
        [{'on': 'E_y', 'schemes': [...]}, ...]
    """
    if isinstance(source, dict):
        return _fix_on_keys(source)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Methodization file not found: {path}")

    # Custom loader to preserve YAML tags as strings
    class TagPreservingLoader(yaml.SafeLoader):
        pass

    def tag_constructor(loader, tag_suffix, node):
        """Preserve YAML tags as tagged strings."""
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
            return {'__yaml_tag__': tag_suffix, 'value': value}
        elif isinstance(node, yaml.MappingNode):
            value = loader.construct_mapping(node)
            return {'__yaml_tag__': tag_suffix, **value}
        return loader.construct_yaml_str(node)

    # Register handler for all tags
    TagPreservingLoader.add_multi_constructor('!', tag_constructor)

    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.load(f, Loader=TagPreservingLoader)

    return _fix_on_keys(data)


def _fix_on_keys(data: Any) -> Any:
    """
    Fix YAML parsing of 'on' key (YAML interprets 'on' as True).

    Recursively converts {True: value} to {'on': value} in method entries.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            # YAML parses 'on' as True, 'off' as False
            if k is True:
                k = 'on'
            elif k is False:
                k = 'off'
            result[k] = _fix_on_keys(v)
        return result
    elif isinstance(data, list):
        return [_fix_on_keys(item) for item in data]
    return data


# -----------------------------------------------------------------------------
# Methodization Functor
# -----------------------------------------------------------------------------

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
    # Load methodization config
    config = load_methodization(methodization_source)
    provided_methods = config.get('methods', [])

    # Extract all valid targets from stage
    stage_targets = extract_stage_targets(stage)
    operator_targets = extract_operator_instances(stage)
    all_targets = stage_targets + operator_targets

    # Build provided map: target → entry
    provided_map = {}
    for entry in provided_methods:
        target = entry.get('on')
        if target in provided_map:
            raise ValueError(f"Duplicate methodization target: {target}")
        provided_map[target] = entry

    # Validate: check for unknown targets in provided
    for target in provided_map:
        if target not in all_targets:
            msg = f"Unknown methodization target: {target}"
            if strict:
                raise ValueError(msg)
            else:
                import warnings
                warnings.warn(msg)

    # Expand to exhaustive table
    expanded_methods = []
    for target in all_targets:
        if target in provided_map:
            expanded_methods.append(provided_map[target])
        else:
            # Fill with empty schemes
            expanded_methods.append({'on': target, 'schemes': []})

    # Optional: validate schemes against registry
    if registry:
        _validate_schemes(expanded_methods, registry)

    # Optional: validate settings symbols
    _validate_settings_symbols(expanded_methods, stage)

    # Create new stage with methods attached (functorial)
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

    # Get declared settings symbols
    declared_settings = set()
    if hasattr(stage, 'symbols') and 'settings' in stage.symbols:
        declared_settings = set(stage.symbols['settings'])

    def extract_symbol_names(value):
        """Recursively extract symbol names from settings value (may be str, list, or nested)."""
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


# -----------------------------------------------------------------------------
# Template Generation
# -----------------------------------------------------------------------------

def emit_methodization_template(stage, stage_name: str = "stage") -> str:
    """
    Generate a methodization.yml template for a stage.

    Lists all targets with `schemes: []` for user to fill in.

    Args:
        stage: SymbolicModel
        stage_name: Name to use in template header

    Returns:
        YAML string template
    """
    stage_targets = extract_stage_targets(stage)
    operator_targets = extract_operator_instances(stage)

    lines = [
        f"# Methodization template for {stage_name}",
        f"# Generated from stage targets + operator instances",
        f"#",
        f"# Fill in schemes for each target as needed.",
        f"# Targets with `schemes: []` will use defaults (if any).",
        f"",
        f"stage: {stage_name}",
        f"",
        f"methods:",
    ]

    # Operator instances first
    if operator_targets:
        lines.append("  # Operator instances (extracted from equation bodies)")
        for target in operator_targets:
            lines.append(f"  - on: {target}")
            lines.append(f"    schemes: []")
            lines.append("")

    # Stage targets
    if stage_targets:
        lines.append("  # Stage labels (equations, movers, sub-equations)")
        for target in stage_targets:
            lines.append(f"  - on: {target}")
            lines.append(f"    schemes: []")
            lines.append("")

    return '\n'.join(lines)
