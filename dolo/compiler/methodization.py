"""
Methodization Functor (spec_0.1d)

Source-level I/O + inspection tools stay here.
The stage verb (methodize) lives in stage_factory/methodize.py.
This file re-exports it for backward compatibility.

Targets can be:
- Equation/builder labels (top-level keys under `equations:`)
- Sub-equation labels via dot notation (`cntn_to_dcsn_builder.InvEuler`)
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
    Forward builders are implied from transitions.

    Args:
        stage: SymbolicModel with parsed YAML

    Returns:
        List of target strings, e.g.:
        ['arvl_to_dcsn_transition', 'cntn_to_dcsn_builder',
         'cntn_to_dcsn_builder.Bellman', 'cntn_to_dcsn_builder.InvEuler', ...]
    """
    targets = []

    equations = _get_equations_block(stage)
    if not equations:
        return targets

    block_labels = []
    for label, value in equations.items():
        block_labels.append(label)
        targets.append(label)

        if isinstance(value, dict):
            for sublabel in value.keys():
                targets.append(f"{label}.{sublabel}")

    for label in list(targets):
        if label.endswith('_transition'):
            forward_builder = label.replace('_transition', '_builder')
            if forward_builder not in targets:
                targets.append(forward_builder)

    # Implied kernel/policy method-bearing nodes (spec 0.3 / spec 0.1d.1), which
    # are not themselves equation labels:
    #   * `evaluate` — the evaluation operator that lowers the value field and
    #     evaluates the selected policy — is implied by any backward evaluation
    #     block or a `policy` block;
    #   * `upper_env` — the optional upper-envelope operator that feeds
    #     `evaluate` (resolving the EGM value correspondence) — is an optional
    #     node of the policy/selection layer, implied whenever a `policy` block
    #     is present (a method only attaches when the model actually declares
    #     one; a policy with no envelope simply never targets it).
    if any(b in block_labels for b in ('cntn_to_dcsn', 'dcsn_to_arvl')) or 'policy' in block_labels:
        if 'evaluate' not in targets:
            targets.append('evaluate')
    if 'policy' in block_labels and 'upper_env' not in targets:
        targets.append('upper_env')

    # Declared exogenous shocks are valid targets for shock-discretisation
    # methodization (spec 0.1d.1 §3: shock_discretisation attaches to the shock
    # declaration at load time, distinct from the `E_{shock}` expectation node).
    try:
        shock_symbols = dict(stage.symbols).get('exogenous') or []
    except Exception:
        shock_symbols = []
    for shock in shock_symbols:
        s = str(shock)
        if s not in targets:
            targets.append(s)

    return targets


def extract_operator_instances(stage) -> List[str]:
    """
    Extract operator instance IDs from equation bodies.

    Finds:
    - expectation operators: ``E_{y}(...)`` → ``'E_y'``
      (multiple subscripts ``E_{w,z}(...)`` → ``'E_w_z'``);
    - maximisation operators: ``max_{c}(...)`` → ``'max_c'`` and
      ``argmax_{c}(...)`` → ``'argmax_c'`` (spec 0.1f) so fine-grain
      maximisation can attach as a named methodization node.

    Args:
        stage: SymbolicModel with parsed YAML

    Returns:
        List of operator instance IDs, e.g.: ['E_y', 'argmax_c', 'max_c']
    """
    operators = set()

    # argmax must be matched before max (max is a substring of argmax); we test
    # argmax first per token so `argmax_{c}` yields 'argmax_c', not 'max_c'.
    expectation_pattern = re.compile(r'E_\{([^}]+)\}\s*\(')
    argmax_pattern = re.compile(r'argmax_\{([^}]+)\}')
    max_pattern = re.compile(r'(?<![A-Za-z])max_\{([^}]+)\}')

    equations = _get_equations_block(stage)
    if not equations:
        return list(operators)

    def _subscript_id(prefix: str, subscript: str) -> str:
        return prefix + subscript.replace(',', '_').replace(' ', '')

    def extract_from_text(text: str):
        for match in expectation_pattern.finditer(text):
            operators.add(_subscript_id('E_', match.group(1)))
        for match in argmax_pattern.finditer(text):
            operators.add(_subscript_id('argmax_', match.group(1)))
        # the negative-lookbehind excludes the `max_` inside `argmax_`
        for match in max_pattern.finditer(text):
            operators.add(_subscript_id('max_', match.group(1)))

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
    import types
    if isinstance(source, (dict, types.MappingProxyType)):
        raw = dict(source) if isinstance(source, types.MappingProxyType) else source
        return _normalize_methods(_fix_on_keys(raw))

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

    return _normalize_methods(_fix_on_keys(data), source=str(path))


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
# Operator-slot (no-schemes) normalization — spec 0.1d.1
# -----------------------------------------------------------------------------

# Inverse of the spec 0.1d.1 §3 "scheme → named-node" table. It maps a named
# node back to the legacy scheme name, so a new per-node entry (which omits the
# scheme name) can be normalized into the legacy `schemes:`-list block that
# every downstream consumer (spec_factory, method_overrides) already reads.
#
# The map is keyed by node *family*: an exact node name, or a prefix for the
# operator-instance families (`E_`, `max_`, `argmax_`). A node not in the table
# keeps `scheme: None` in the synthesised block — the method tag is still the
# load-bearing field, and the scheme name is only used for legacy override
# addressing.
_NODE_TO_SCHEME_EXACT = {
    "cntn_to_dcsn_builder": "bellman_backward",
    "dcsn_to_arvl_builder": "bellman_backward",
    "policy": "bellman_backward",
    "evaluate": "interpolation",
    "upper_env": "upper_envelope",
    "arvl_to_dcsn_builder": "simulation",
    "dcsn_to_cntn_builder": "simulation",
}

_NODE_TO_SCHEME_PREFIX = (
    ("argmax_", "maximization"),
    ("max_", "maximization"),
    ("E_", "expectation"),
)


def _scheme_for_node(node: str) -> Optional[str]:
    """Map a named node to its legacy scheme name (spec 0.1d.1 §3), or None."""
    if not isinstance(node, str):
        return None
    if node in _NODE_TO_SCHEME_EXACT:
        return _NODE_TO_SCHEME_EXACT[node]
    for prefix, scheme in _NODE_TO_SCHEME_PREFIX:
        if node.startswith(prefix):
            return scheme
    return None


def _entry_is_new_surface(entry: dict) -> bool:
    """A per-named-node (no-schemes) entry carries `method:` and no `schemes:`."""
    return "method" in entry and "schemes" not in entry


def _normalize_entry(entry: dict, source: Optional[str] = None) -> dict:
    """
    Normalize one methodization entry to the canonical `schemes:`-list shape.

    - Legacy entry (has `schemes:`) — returned unchanged.
    - New per-node entry (`method: !tag`, optional `settings`/`equations`/
      `handler`, no `schemes:`) — folded into a single synthetic scheme block,
      with `scheme:` derived from the node→scheme inverse map.
    - Bare entry (`on:` only, no `schemes:`, no `method:`) — gets `schemes: []`.
    """
    if not isinstance(entry, dict):
        return entry

    # Legacy surface: leave the schemes list exactly as authored.
    if "schemes" in entry:
        return entry

    on = entry.get("on")

    # New per-node surface: synthesise one scheme block.
    if "method" in entry:
        block = {"scheme": _scheme_for_node(on), "method": entry["method"]}
        if "settings" in entry:
            block["settings"] = entry["settings"]
        if "equations" in entry:
            block["equations"] = entry["equations"]
        # `handler:` is the new name for the old `tool:` slot (spec 0.1d.1 §6).
        # Carry it under both keys so old (`tool`) and new (`handler`) consumers
        # both resolve.
        if "handler" in entry:
            block["handler"] = entry["handler"]
            block["tool"] = entry["handler"]
        elif "tool" in entry:
            block["tool"] = entry["tool"]
            block["handler"] = entry["tool"]

        normalized = {"on": on, "schemes": [block]}
        # Preserve any other authoring keys on the entry untouched.
        for k, v in entry.items():
            if k not in ("on", "method", "settings", "equations", "handler", "tool"):
                normalized[k] = v
        return normalized

    # Bare entry: no method attached.
    normalized = dict(entry)
    normalized.setdefault("schemes", [])
    return normalized


def _normalize_methods(data: Any, source: Optional[str] = None) -> Any:
    """
    Normalize a loaded methodization config so every method entry carries a
    `schemes:`-list (the canonical internal shape). Backwards-compatible: legacy
    entries pass through unchanged; new per-node entries are folded in.

    A deprecation note is emitted (once per load) if any legacy `scheme:` block
    is encountered, to steer authors toward the operator-slot surface.
    """
    if not isinstance(data, dict):
        return data

    methods = data.get("methods")
    if not isinstance(methods, list):
        return data

    legacy_seen = False
    normalized_methods = []
    for entry in methods:
        if isinstance(entry, dict) and "schemes" in entry:
            for block in entry["schemes"]:
                if isinstance(block, dict) and "scheme" in block:
                    legacy_seen = True
                    break
        normalized_methods.append(_normalize_entry(entry, source=source))

    if legacy_seen:
        import warnings
        where = f" ({source})" if source else ""
        warnings.warn(
            "Methodization uses the legacy `scheme:`/`schemes:` surface"
            f"{where}; migrate to the operator-slot form "
            "(`on: <node>` / `method: !tag`, no `schemes:` list) — spec 0.1d.1.",
            DeprecationWarning,
            stacklevel=2,
        )

    data = dict(data)
    data["methods"] = normalized_methods
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
        lines.append("  # Stage labels (equations, builders, sub-equations)")
        for target in stage_targets:
            lines.append(f"  - on: {target}")
            lines.append(f"    schemes: []")
            lines.append("")

    return '\n'.join(lines)
