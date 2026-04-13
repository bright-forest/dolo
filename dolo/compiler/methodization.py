"""
Methodization Functor (spec_0.1d)

Source-level I/O + inspection tools stay here.
The stage verb (methodize) lives in stage_factory/methodize.py.
This file re-exports it for backward compatibility.

Targets can be:
- Equation/mover labels (top-level keys under `equations:`)
- Sub-equation labels via dot notation (`cntn_to_dcsn_mover.InvEuler`)
- Operator instance IDs extracted from equation bodies (`E_y`, `E_w`)
"""

import re
from pathlib import Path
from typing import Union, Dict, List, Any, Optional

import yaml

# Re-export stage verb (spec 0.1r — code lives in stage_factory/)
from .stage_factory.methodize import methodize  # noqa: F401

__all__ = [
    "load_methodization",
    "methodize",
    "extract_stage_targets",
    "extract_operator_instances",
    "emit_methodization_template",
]


# -----------------------------------------------------------------------------
# Target Extraction — inspection tools, stay here
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

    equations = _get_equations_block(stage)
    if not equations:
        return targets

    for label, value in equations.items():
        targets.append(label)

        if isinstance(value, dict):
            for sublabel in value.keys():
                targets.append(f"{label}.{sublabel}")

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

    expectation_pattern = re.compile(r'E_\{([^}]+)\}\s*\(')

    equations = _get_equations_block(stage)
    if not equations:
        return list(operators)

    def extract_from_text(text: str):
        for match in expectation_pattern.finditer(text):
            subscript = match.group(1)
            op_id = 'E_' + subscript.replace(',', '_').replace(' ', '')
            operators.add(op_id)

    def walk_equations(obj):
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
        from dolang.yaml_nodes import mapping_get, mapping_items
        import yaml.nodes

        data = stage.data
        if isinstance(data, yaml.nodes.MappingNode):
            eqs_node = mapping_get(data, 'equations')
            if eqs_node is None:
                return {}
            result = {}
            for key_node, val_node in eqs_node.value:
                key = key_node.value
                if isinstance(val_node, yaml.nodes.ScalarNode):
                    result[key] = val_node.value
                elif isinstance(val_node, yaml.nodes.MappingNode):
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
# Methodization Loading — source-level I/O, stays here
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
    """
    if isinstance(source, dict):
        return _fix_on_keys(source)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Methodization file not found: {path}")

    class TagPreservingLoader(yaml.SafeLoader):
        pass

    def tag_constructor(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
            return {'__yaml_tag__': tag_suffix, 'value': value}
        elif isinstance(node, yaml.MappingNode):
            value = loader.construct_mapping(node)
            return {'__yaml_tag__': tag_suffix, **value}
        return loader.construct_yaml_str(node)

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
# Template Generation — authoring helper, stays here
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

    if operator_targets:
        lines.append("  # Operator instances (extracted from equation bodies)")
        for target in operator_targets:
            lines.append(f"  - on: {target}")
            lines.append(f"    schemes: []")
            lines.append("")

    if stage_targets:
        lines.append("  # Stage labels (equations, movers, sub-equations)")
        for target in stage_targets:
            lines.append(f"  - on: {target}")
            lines.append(f"    schemes: []")
            lines.append("")

    return '\n'.join(lines)
