"""
Dolo+ to Dolo Translator.

Translates Dolo+ adc-stage models to vanilla Dolo models suitable for
various solution methods.

Usage:
    from dolo.compiler.model_import import yaml_import
    from dolo.compiler.doloplus_translator import doloplus_to_dolo

    model_plus = yaml_import(path, compile_functions=False)
    model_dolo = doloplus_to_dolo(model_plus, method="egm")
"""

from typing import Any, Literal
import copy
import re

from dolang.yaml_nodes import (
    mapping_get,
    mapping_items,
    scalar_value,
    sequence_values,
)
from yaml import ScalarNode, MappingNode, SequenceNode

from dolo.compiler.model import Model


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def doloplus_to_dolo(
    model_plus: Any,
    method: Literal["egm"] = "egm",
) -> Model:
    """
    Translate a Dolo+ model to a vanilla Dolo model.

    Args:
        model_plus: Parsed Dolo+ Model (with compile_functions=False)
        method: Target solution method. Currently supports:
            - "egm": Endogenous Grid Method

    Returns:
        Vanilla Dolo Model ready for compilation and solving

    Raises:
        ValueError: If the input model is not valid or method is unsupported

    Example:
        >>> from dolo.compiler.model_import import yaml_import
        >>> from dolo.compiler.doloplus_translator import doloplus_to_dolo
        >>>
        >>> model_plus = yaml_import("model_doloplus.yaml", compile_functions=False)
        >>> model_dolo = doloplus_to_dolo(model_plus, method="egm")
        >>>
        >>> # Now use vanilla Dolo solver
        >>> from dolo.algos.egm import egm
        >>> result = egm(model_dolo)
    """
    # Validate the model
    _validate_doloplus_model(model_plus)

    # Extract common structures
    context = _build_translation_context(model_plus)

    if method == "egm":
        return _translate_for_egm(model_plus, context)
    elif method == "vfi":
        raise NotImplementedError("VFI translator not yet implemented")
    elif method == "time_iteration":
        raise NotImplementedError("Time iteration translator not yet implemented")
    else:
        raise ValueError(f"Unknown solution method: {method}")


# ---------------------------------------------------------------------------
# Validation and Context Building
# ---------------------------------------------------------------------------


def _validate_doloplus_model(model) -> None:
    """Validate that the model is a proper Dolo+ model."""
    dp = mapping_get(model.data, "dolo_plus")
    if dp is None:
        raise ValueError("Model is not a Dolo+ model: missing 'dolo_plus' block")

    dialect = scalar_value(mapping_get(dp, "dialect"))
    if dialect != "adc-stage":
        raise ValueError(f"Unsupported Dolo+ dialect: {dialect}. Expected 'adc-stage'")

    version = scalar_value(mapping_get(dp, "version"))
    if version not in ("0.1", 0.1):
        raise ValueError(f"Unsupported Dolo+ version: {version}. Expected '0.1'")


def _build_translation_context(model) -> dict:
    """Build lookup tables and context for translation."""
    symbol_groups = dict(model.symbols)

    dp = mapping_get(model.data, "dolo_plus")
    validation = mapping_get(dp, "validation")
    slot_map = mapping_get(dp, "slot_map")
    eq_symbols = mapping_get(dp, "equation_symbols")

    # Index aliases: perch tag → slot
    index_aliases = {}
    if validation is not None:
        aliases_node = mapping_get(validation, "index_aliases")
        if aliases_node is not None:
            for k, v in mapping_items(aliases_node):
                index_aliases[k] = int(scalar_value(v))

    # Equation symbols: label → canonical
    eq_symbol_map = {}
    if eq_symbols is not None:
        for k, v in mapping_items(eq_symbols):
            eq_symbol_map[k] = scalar_value(v)

    # Prestate rename map
    prestate_rename = _build_prestate_rename_map(slot_map)

    return {
        "symbol_groups": symbol_groups,
        "index_aliases": index_aliases,
        "eq_symbols": eq_symbol_map,
        "prestate_rename": prestate_rename,
    }


def _build_prestate_rename_map(slot_map) -> dict[str, str]:
    """Build mapping from prestate symbols to poststate symbols."""
    if slot_map is None:
        return {}

    rename_map = {}
    prestate_tokens = []
    poststate_tokens = []

    for key, val in mapping_items(slot_map):
        if key == "x[-1]":
            tokens_node = mapping_get(val, "tokens")
            if tokens_node is not None:
                prestate_tokens = [scalar_value(t) for t in sequence_values(tokens_node)]
        elif key == "x[+1]":
            tokens_node = mapping_get(val, "tokens")
            if tokens_node is not None:
                poststate_tokens = [scalar_value(t) for t in sequence_values(tokens_node)]

    for pre, post in zip(prestate_tokens, poststate_tokens):
        rename_map[pre] = post

    return rename_map


# ---------------------------------------------------------------------------
# EGM Translation
# ---------------------------------------------------------------------------

# Mapping from Dolo+ canonical symbols to Dolo block names
_TRANSITION_MAP = {
    "g_ad": "half_transition",
    "g_de": "auxiliary_direct_egm",
    "g_ed": "reverse_state",
}


def _translate_for_egm(model_plus, context: dict) -> Model:
    """Translate Dolo+ model to vanilla Dolo for EGM solver."""
    symbols = _translate_symbols_egm(context)
    equations = _translate_equations_egm(model_plus.equations, context)

    return _build_model(model_plus, symbols, equations)


def _translate_symbols_egm(context: dict) -> dict[str, list[str]]:
    """Translate Dolo+ symbol groups to Dolo symbol groups for EGM."""
    symbol_groups = context["symbol_groups"]
    symbols = {}

    # Direct mappings (drop prestate, values, shadow_value)
    for group in ("exogenous", "states", "poststates", "controls", "parameters"):
        if group in symbol_groups:
            symbols[group] = list(symbol_groups[group])

    # Create expectations group
    symbols["expectations"] = ["mr"]

    return symbols


def _translate_equations_egm(source_eqs: dict, context: dict) -> dict[str, str]:
    """Translate Dolo+ equations to Dolo equation blocks for EGM."""
    eq_symbols = context["eq_symbols"]
    equations = {}

    for label, payload in source_eqs.items():
        canonical = eq_symbols.get(label)
        if canonical is None:
            continue

        if canonical in _TRANSITION_MAP:
            block_name = _TRANSITION_MAP[canonical]
            equations[block_name] = _translate_transition(payload, context)

        elif canonical == "T_ed":
            # Mover: extract InvEuler → direct_response_egm
            if "InvEuler" in payload:
                equations["direct_response_egm"] = _translate_inv_euler(
                    payload["InvEuler"], context
                )

        # T_da.ShadowBellman is used in expectation synthesis below

    # Synthesize expectation block
    equations["expectation"] = _synthesize_expectation(source_eqs, context)

    # Synthesize arbitrage block with complementarity for EGM bounds
    states = context["symbol_groups"].get("states", [])
    controls = context["symbol_groups"].get("controls", [])

    if states and len(states) == 1 and len(controls) == 1:
        c, s = controls[0], states[0]
        equations["arbitrage"] = f"0 | 0.0<={c}[t]<={s}[t]"
    else:
        arb_eqs = [f"0 | 0.0<={c}[t]<=1e10" for c in controls]
        equations["arbitrage"] = "\n".join(arb_eqs)

    return equations


def _translate_transition(payload: list[str], context: dict) -> str:
    """Translate a transition equation with perch→time conversion."""
    translated = []
    for eq in payload:
        eq_translated = _perch_to_time(
            eq,
            context["symbol_groups"],
            context["prestate_rename"],
            context["index_aliases"],
        )
        translated.append(eq_translated)
    return "\n".join(translated)


def _translate_inv_euler(eqs: list[str], context: dict) -> str:
    """Translate InvEuler sub-equation to direct_response_egm."""
    translated = []
    for eq in eqs:
        # Replace dV with mr
        eq = _rename_symbols(eq, {"dV": "mr"})

        # Remove β (Dolo's mr already includes β)
        eq = re.sub(r'\(β\)\s*\*\s*\(mr', '(mr', eq)
        eq = re.sub(r'\(β\)\s*\*\s*mr', 'mr', eq)
        eq = re.sub(r'β\s*\*\s*mr', 'mr', eq)

        # For EGM InvEuler: both c[_cntn] and mr[_cntn] map to [t]
        eq = eq.replace("[_cntn]", "[t]")

        # Handle any remaining perch tags
        eq = _perch_to_time(
            eq,
            context["symbol_groups"],
            context["prestate_rename"],
            context["index_aliases"],
        )
        translated.append(eq)

    return "\n".join(translated)


def _synthesize_expectation(source_eqs: dict, context: dict) -> str:
    """Synthesize Dolo expectation block from ShadowBellman sub-equations."""
    # Extract integrand from T_ed.ShadowBellman: dV[_dcsn] = (c[_dcsn])^(-γ)
    t_ed = source_eqs.get("cntn_to_dcsn_mover", {})
    shadow_ed = t_ed.get("ShadowBellman", [])
    if not shadow_ed:
        raise ValueError("Missing T_ed.ShadowBellman for expectation synthesis")

    integrand_eq = shadow_ed[0]
    integrand = _extract_rhs(integrand_eq)

    # Shift integrand to next period: c[_dcsn] → c[t+1]
    integrand_shifted = _shift_perch_to_next_period(integrand, context["index_aliases"])

    # Extract factors from T_da.ShadowBellman: dV[_arvl] = r * E_{y}(dV[_dcsn])
    t_da = source_eqs.get("dcsn_to_arvl_mover", {})
    shadow_da = t_da.get("ShadowBellman", [])
    if not shadow_da:
        raise ValueError("Missing T_da.ShadowBellman for expectation synthesis")

    factor_eq = shadow_da[0]
    rhs = _extract_rhs(factor_eq)

    # Extract multiplicative factors (everything except E_{...}(...))
    factors = _extract_multiplicative_factors(
        rhs, r'E_\{[^}]+\}\([^)]+\)|E_[a-zA-Z][a-zA-Z0-9_]*\([^)]+\)'
    )

    # Build result: mr[t] = β * <integrand> * <factors>
    result = f"mr[t] = β * ({integrand_shifted})"
    for factor in factors:
        result = f"{result} * {factor}"

    return result


# ---------------------------------------------------------------------------
# Transform Utilities
# ---------------------------------------------------------------------------


def _perch_to_time(
    eq_str: str,
    symbol_groups: dict[str, list[str]],
    prestate_rename: dict[str, str],
    index_aliases: dict[str, int],
) -> str:
    """Convert perch tags to time subscripts with group-aware logic."""
    poststates = set(symbol_groups.get("poststates", []))
    prestates = set(prestate_rename.keys())

    pattern = r'(\w+)\[(_arvl|_dcsn|_cntn)\]'

    def replacer(m: re.Match) -> str:
        name, tag = m.groups()
        slot = index_aliases.get(tag, 0)

        # Handle prestate rename: b[_arvl] → a[t-1]
        if name in prestates:
            new_name = prestate_rename[name]
            return f"{new_name}[t-1]"

        # Handle poststates: a[_cntn] → a[t] (not a[t+1])
        if name in poststates and tag == "_cntn":
            return f"{name}[t]"

        # Default mapping
        if slot == 0:
            return f"{name}[t]"
        elif slot > 0:
            return f"{name}[t+{slot}]"
        else:
            return f"{name}[t{slot}]"

    return re.sub(pattern, replacer, eq_str)


def _shift_perch_to_next_period(eq_str: str, index_aliases: dict[str, int]) -> str:
    """Shift perch-tagged variables to next-period time indices."""
    pattern = r'\[(_arvl|_dcsn|_cntn)\]'

    def replacer(m: re.Match) -> str:
        tag = m.group(1)
        if tag == "_arvl":
            return "[t]"
        else:  # _dcsn or _cntn
            return "[t+1]"

    return re.sub(pattern, replacer, eq_str)


def _rename_symbols(eq_str: str, mapping: dict[str, str]) -> str:
    """Rename symbols in an equation string."""
    result = eq_str
    for old, new in mapping.items():
        pattern = rf'\b{re.escape(old)}\b'
        result = re.sub(pattern, new, result)
    return result


def _extract_rhs(eq_str: str) -> str:
    """Extract the right-hand side of an equation."""
    if "=" not in eq_str:
        return eq_str.strip()
    return eq_str.split("=", 1)[1].strip()


def _extract_multiplicative_factors(eq_str: str, exclude_pattern: str) -> list[str]:
    """Extract multiplicative factors from an equation, excluding a pattern."""
    rhs = _extract_rhs(eq_str)
    cleaned = re.sub(exclude_pattern, '', rhs)
    parts = cleaned.split('*')
    factors = []
    for p in parts:
        stripped = p.strip()
        if stripped and stripped not in ('', '()', '( )'):
            factors.append(stripped)
    return factors


# ---------------------------------------------------------------------------
# Model Building
# ---------------------------------------------------------------------------


def _build_model(model_plus, symbols: dict, equations: dict) -> Model:
    """Build the output vanilla Dolo model."""
    new_data = copy.deepcopy(model_plus.data)

    # Build new symbols node
    symbols_items = []
    for group, syms in symbols.items():
        key_node = ScalarNode(tag="tag:yaml.org,2002:str", value=group)
        seq_items = [ScalarNode(tag="tag:yaml.org,2002:str", value=s) for s in syms]
        val_node = SequenceNode(tag="tag:yaml.org,2002:seq", value=seq_items)
        symbols_items.append((key_node, val_node))

    new_symbols = MappingNode(tag="tag:yaml.org,2002:map", value=symbols_items)

    # Build new equations node
    eq_items = []
    for block_name, eq_str in equations.items():
        key_node = ScalarNode(tag="tag:yaml.org,2002:str", value=block_name)
        val_node = ScalarNode(tag="tag:yaml.org,2002:str", value=eq_str, style="|")
        eq_items.append((key_node, val_node))

    new_equations = MappingNode(tag="tag:yaml.org,2002:map", value=eq_items)

    # Replace in data, removing dolo_plus block
    new_data_items = []
    for key, val in new_data.value:
        if key.value == "symbols":
            new_data_items.append((key, new_symbols))
        elif key.value == "equations":
            new_data_items.append((key, new_equations))
        elif key.value == "dolo_plus":
            continue  # Remove dolo_plus block
        else:
            new_data_items.append((key, val))

    new_data.value = new_data_items

    return Model(
        new_data,
        check=False,
        filename=model_plus._filename,
        compile_functions=True
    )


__all__ = ["doloplus_to_dolo"]
