"""
Core translation logic for Dolo+ to Dolo conversion.

This module provides the main entry point doloplus_to_dolo() and orchestrates
the translation process using configurable mappings.

Translation Pipeline:
    1. validate_model    - Verify Dolo+ model structure
    2. build_context     - Extract symbol groups, aliases, equation mappings
    3. translate_symbols - Filter and transform symbol groups
    4. translate_equations - Transform equations using mappings
    5. assemble_model    - Build vanilla Dolo Model object
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import copy

import yaml
from yaml import ScalarNode, MappingNode, SequenceNode

from dolang.yaml_nodes import (
    mapping_get,
    mapping_items,
    scalar_value,
    sequence_values,
)

from dolo.compiler.model import Model

from .transforms import (
    perch_to_time,
    shift_perch_tags,
    rename_symbols,
    remove_discount_factor,
    extract_rhs,
    extract_factors,
    join_equations,
)


# =============================================================================
# PUBLIC API
# =============================================================================

MappingTablesSource = Union[Dict[str, Any], str, Path]


def load_mapping_tables(source: MappingTablesSource) -> Dict[str, Any]:
    """
    Load transformation mapping tables from a dict, file path, or folder path.

    If `source` is a directory, we look for `mapping_tables.yaml` inside it.
    """
    if isinstance(source, dict):
        return source

    path = Path(source)
    if path.is_dir():
        path = path / "mapping_tables.yaml"

    with path.open("r", encoding="utf-8") as f:
        tables = yaml.safe_load(f)

    if not isinstance(tables, dict):
        raise ValueError(f"Invalid mapping tables payload at {path}: expected YAML mapping.")

    return tables


def doloplus_to_dolo(
    model_plus: Any,
    *,
    mapping_tables: MappingTablesSource,
    compile_functions: bool = True,
) -> Model:
    """
    Translate a Dolo+ model to vanilla Dolo using external mapping tables.

    Args:
        model_plus: Parsed Dolo+ Model (with compile_functions=False)
        mapping_tables: Mapping tables dict, YAML file path, or folder containing
            `mapping_tables.yaml`. All transformation behavior should be defined
            in these tables (no Python defaults).
        compile_functions: Whether to compile the output model functions.

    Returns:
        Vanilla Dolo Model ready for compilation and solving

    Raises:
        ValueError: If model is not valid Dolo+ format

    Example:
        >>> from dolo.compiler.model_import import yaml_import
        >>> from dolo.compiler.doloplus_translator import doloplus_to_dolo
        >>>
        >>> model_plus = yaml_import("model.yaml", compile_functions=False)
        >>> model_dolo = doloplus_to_dolo(model_plus, mapping_tables="path/to/mapping_tables.yaml")
    """
    tables = load_mapping_tables(mapping_tables)

    # Required sections (fail fast; avoid silent defaults)
    perch_offsets = tables.get("PERCH_TO_TIME_OFFSET")
    transition_map = tables.get("TRANSITION_TO_BLOCK")
    symbol_groups_keep = tables.get("SYMBOL_GROUPS_KEEP")
    pipelines = tables.get("PIPELINES")

    missing = [
        k
        for (k, v) in [
            ("PERCH_TO_TIME_OFFSET", perch_offsets),
            ("TRANSITION_TO_BLOCK", transition_map),
            ("SYMBOL_GROUPS_KEEP", symbol_groups_keep),
            ("PIPELINES", pipelines),
        ]
        if v is None
    ]
    if missing:
        raise ValueError(f"Missing required mapping table keys: {', '.join(missing)}")

    # Step 1: Validate
    validate_model(model_plus)

    # Step 2: Build context
    context = build_context(model_plus, perch_offsets)

    # Step 3: Translate symbols
    symbols = translate_symbols(
        context,
        keep_groups=tuple(symbol_groups_keep),
        add_groups=tables.get("SYMBOL_GROUPS_ADD", {}) or {},
    )

    # Step 4: Translate equations
    equations = translate_equations(
        source_eqs=model_plus.equations,
        context=context,
        tables=tables,
    )

    # Step 5: Assemble output model
    return assemble_model(
        model_plus,
        symbols,
        equations,
        compile_functions=compile_functions,
    )


# =============================================================================
# VALIDATION
# =============================================================================

def validate_model(model: Any) -> None:
    """
    Validate that the model is a proper Dolo+ model.

    Checks:
        - Has 'dolo_plus' block
        - Dialect is 'adc-stage'
        - Version is supported

    Args:
        model: Parsed model object

    Raises:
        ValueError: If validation fails
    """
    dp = mapping_get(model.data, "dolo_plus")
    if dp is None:
        raise ValueError("Model is not a Dolo+ model: missing 'dolo_plus' block")

    dialect = scalar_value(mapping_get(dp, "dialect"))
    if dialect != "adc-stage":
        raise ValueError(
            f"Unsupported Dolo+ dialect: {dialect}. Expected 'adc-stage'"
        )

    version = scalar_value(mapping_get(dp, "version"))
    if version not in ("0.1", 0.1):
        raise ValueError(
            f"Unsupported Dolo+ version: {version}. Expected '0.1'"
        )


# =============================================================================
# CONTEXT BUILDING
# =============================================================================

def build_context(model: Any, perch_offsets: Dict[str, int]) -> Dict:
    """
    Build translation context from model.

    Extracts:
        - symbol_groups: Dict of symbol group name → symbol list
        - index_aliases: Perch tag → slot number mapping
        - eq_symbols: Equation label → canonical symbol mapping
        - prestate_rename: Prestate symbol → poststate symbol mapping

    Args:
        model: Parsed Dolo+ model
        perch_offsets: Perch → time offset mapping

    Returns:
        Context dict with extracted data
    """
    symbol_groups = dict(model.symbols)

    dp = mapping_get(model.data, "dolo_plus")
    validation = mapping_get(dp, "validation")
    slot_map = mapping_get(dp, "slot_map")
    eq_symbols = mapping_get(dp, "equation_symbols")

    # Index aliases: perch tag → slot
    index_aliases = dict(perch_offsets)  # Start with defaults
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


def _build_prestate_rename_map(slot_map) -> Dict[str, str]:
    """
    Build mapping from prestate symbols to poststate symbols.

    Extracts from slot_map:
        x[-1].tokens → prestate symbols
        x[+1].tokens → poststate symbols

    Args:
        slot_map: YAML node with slot definitions

    Returns:
        Dict mapping prestate names to poststate names
    """
    if slot_map is None:
        return {}

    prestate_tokens = []
    poststate_tokens = []

    for key, val in mapping_items(slot_map):
        if key == "x[-1]":
            tokens_node = mapping_get(val, "tokens")
            if tokens_node is not None:
                prestate_tokens = [
                    scalar_value(t) for t in sequence_values(tokens_node)
                ]
        elif key == "x[+1]":
            tokens_node = mapping_get(val, "tokens")
            if tokens_node is not None:
                poststate_tokens = [
                    scalar_value(t) for t in sequence_values(tokens_node)
                ]

    # Zip into rename map
    rename_map = {}
    for pre, post in zip(prestate_tokens, poststate_tokens):
        rename_map[pre] = post

    return rename_map


# =============================================================================
# SYMBOL TRANSLATION
# =============================================================================

def translate_symbols(
    context: Dict,
    keep_groups: Tuple[str, ...],
    add_groups: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """
    Translate Dolo+ symbol groups to Dolo symbol groups.

    Mapping-table driven:
      - keep only specified groups
      - add any explicit symbol groups (e.g., expectations)

    Args:
        context: Translation context
        keep_groups: Tuple of group names to keep
        add_groups: Mapping of group name → symbol list to add

    Returns:
        Dict of group name → symbol list for Dolo
    """
    symbol_groups = context["symbol_groups"]
    symbols = {}

    # Keep specified groups
    for group in keep_groups:
        if group in symbol_groups:
            symbols[group] = list(symbol_groups[group])

    # Add requested groups (overrides if already present)
    for group, syms in add_groups.items():
        symbols[group] = list(syms)

    return symbols


# =============================================================================
# EQUATION TRANSLATION
# =============================================================================

def translate_equations(
    source_eqs: Dict,
    context: Dict,
    tables: Dict[str, Any],
) -> Dict[str, str]:
    """
    Translate all Dolo+ equation blocks to Dolo format.

    Args:
        source_eqs: Dict of equation label → equations
        context: Translation context
        tables: Mapping tables (YAML dict)

    Returns:
        Dict of Dolo block name → equation string
    """
    eq_symbols = context["eq_symbols"]

    transition_map: Dict[str, str] = tables.get("TRANSITION_TO_BLOCK") or {}
    mover_map: Dict[str, Dict[str, str]] = tables.get("MOVER_TO_BLOCK") or {}
    symbol_renames: Dict[str, str] = tables.get("SYMBOL_RENAMES") or {}

    perch_offsets: Dict[str, int] = tables.get("PERCH_TO_TIME_OFFSET") or {}

    pipelines = tables.get("PIPELINES") or {}
    transition_pipeline = pipelines.get("transitions")
    mover_pipeline = pipelines.get("movers")
    if transition_pipeline is None or mover_pipeline is None:
        raise ValueError(
            "Missing PIPELINES configuration. Expected keys: PIPELINES.transitions, PIPELINES.movers."
        )

    mover_perch_overrides = tables.get("MOVER_PERCH_OFFSETS_OVERRIDE") or {}

    equations: Dict[str, str] = {}

    def apply_pipeline(
        eq: str,
        pipeline: List[str],
        *,
        perch_offsets_local: Dict[str, int],
    ) -> str:
        out = eq
        for step in pipeline:
            step_name = step
            step_cfg: Dict[str, Any] = {}
            if isinstance(step, dict):
                if len(step) != 1:
                    raise ValueError(f"Invalid pipeline step mapping: {step!r}")
                step_name, step_cfg = next(iter(step.items()))
                if step_cfg is None:
                    step_cfg = {}
                elif not isinstance(step_cfg, dict):
                    # Allow scalar payloads for convenience (e.g. {remove_discount_factor: β})
                    step_cfg = {"value": step_cfg}

            if step_name == "rename_symbols":
                out = rename_symbols(out, symbol_renames)
            elif step_name == "remove_discount_factor":
                discount_symbol = step_cfg.get("discount_symbol", step_cfg.get("value"))
                if discount_symbol is None:
                    discount_symbol = tables.get("DISCOUNT_SYMBOL")
                if discount_symbol is None:
                    raise ValueError(
                        "remove_discount_factor requires `DISCOUNT_SYMBOL` in mapping tables "
                        "or an inline step config, e.g. {remove_discount_factor: {discount_symbol: β}}."
                    )
                out = remove_discount_factor(out, discount_symbol=str(discount_symbol))
            elif step_name == "perch_to_time":
                out = perch_to_time(
                    out,
                    context["symbol_groups"],
                    context["prestate_rename"],
                    perch_offsets_local,
                )
            else:
                raise ValueError(f"Unknown pipeline transform: {step_name!r}")
        return out

    for label, payload in source_eqs.items():
        canonical = eq_symbols.get(label)
        if canonical is None:
            continue

        # Transition equations (list[str])
        if canonical in transition_map:
            block_name = transition_map[canonical]
            if not block_name:
                continue
            if not isinstance(payload, list):
                raise ValueError(
                    f"Expected list payload for transition '{label}', got {type(payload)}"
                )
            offsets_local = dict(perch_offsets)
            translated = [
                apply_pipeline(eq, transition_pipeline, perch_offsets_local=offsets_local)
                for eq in payload
            ]
            equations[block_name] = join_equations(translated)
            continue

        # Mover sub-equations (dict[subeq -> list[str]])
        if canonical in mover_map:
            if not isinstance(payload, dict):
                raise ValueError(
                    f"Expected mapping payload for mover '{label}', got {type(payload)}"
                )
            submap = mover_map[canonical] or {}
            for subeq, target_block in submap.items():
                eq_lines = payload.get(subeq)
                if not eq_lines:
                    continue
                if not isinstance(eq_lines, list):
                    raise ValueError(
                        f"Expected list payload for mover sub-equation '{label}.{subeq}', got {type(eq_lines)}"
                    )

                # Allow per-(canonical, subeq) perch-offset overrides.
                overrides = (
                    mover_perch_overrides.get(canonical, {}).get(subeq, {}) or {}
                )
                offsets_local = dict(perch_offsets)
                offsets_local.update({k: int(v) for k, v in overrides.items()})

                translated = [
                    apply_pipeline(eq, mover_pipeline, perch_offsets_local=offsets_local)
                    for eq in eq_lines
                ]

                # Targets starting with '_' are treated as internal (not emitted).
                if target_block and not str(target_block).startswith("_"):
                    equations[target_block] = join_equations(translated)

    # Optional synthesized blocks (fully configured in tables)
    expectation_config = tables.get("EXPECTATION_CONFIG")
    if expectation_config is not None:
        out_block = expectation_config.get("output_block", "expectation")
        equations[out_block] = synthesize_expectation(
            source_eqs, context, expectation_config
        )

    arbitrage_config = tables.get("ARBITRAGE_CONFIG")
    if arbitrage_config is not None:
        out_block = arbitrage_config.get("output_block", "arbitrage")
        equations[out_block] = _synthesize_arbitrage(context, arbitrage_config)

    # Verbatim blocks injected by mapping tables (may override synthesized ones)
    extra_blocks = tables.get("EXTRA_EQUATION_BLOCKS") or {}
    for block_name, payload in extra_blocks.items():
        if payload is None:
            continue
        if isinstance(payload, str):
            equations[block_name] = payload
        elif isinstance(payload, list):
            equations[block_name] = join_equations([str(x) for x in payload])
        else:
            raise ValueError(
                f"Invalid EXTRA_EQUATION_BLOCKS payload for {block_name!r}: {type(payload)}"
            )

    return equations


def synthesize_expectation(
    source_eqs: Dict,
    context: Dict,
    config: Dict,
) -> str:
    """
    Synthesize Dolo expectation block from mover equations.

    Uses config to determine:
        - Where to extract integrand from
        - Where to extract factors from
        - Output template format

    Args:
        source_eqs: Source equations dict
        context: Translation context
        config: Expectation synthesis config
    Returns:
        Expectation equation string
    """
    # Extract integrand from T_ed source
    t_ed_config = config["T_ed"]
    t_ed = source_eqs.get(t_ed_config["mover"], {})
    shadow_ed = t_ed.get(t_ed_config["sub_equation"], [])

    if not shadow_ed:
        raise ValueError(
            f"Missing {t_ed_config['mover']}.{t_ed_config['sub_equation']} "
            "for expectation synthesis"
        )

    integrand_eq = shadow_ed[0]
    integrand = extract_rhs(integrand_eq)

    # Shift integrand perch tags to time indices (mapping-table driven)
    shift_offsets = config.get("integrand_shift_offsets")
    if shift_offsets is None:
        raise ValueError(
            "EXPECTATION_CONFIG is missing `integrand_shift_offsets` (required)."
        )
    integrand_shifted = shift_perch_tags(
        integrand, {k: int(v) for k, v in shift_offsets.items()}
    )

    # Extract factors from T_da source
    t_da_config = config["T_da"]
    t_da = source_eqs.get(t_da_config["mover"], {})
    shadow_da = t_da.get(t_da_config["sub_equation"], [])

    if not shadow_da:
        raise ValueError(
            f"Missing {t_da_config['mover']}.{t_da_config['sub_equation']} "
            "for expectation synthesis"
        )

    factor_eq = shadow_da[0]
    factors = extract_factors(factor_eq, config["exclude_pattern"])

    # Build result using template
    factors_str = " * ".join(factors) if factors else "1"
    result = config["output_template"].format(
        integrand=integrand_shifted,
        factors=factors_str,
    )

    return result


def _synthesize_arbitrage(context: Dict, config: Dict[str, Any]) -> str:
    """
    Synthesize arbitrage block with complementarity bounds.

    Mapping-table driven (see ARBITRAGE_CONFIG).

    Args:
        context: Translation context
        config: Arbitrage synthesis config

    Returns:
        Arbitrage equation string
    """
    states = context["symbol_groups"].get("states", [])
    controls = context["symbol_groups"].get("controls", [])

    template = config.get("template", "0 | {lower}<={control}[t]<={upper}")
    default_lower = config.get("default_lower", "0.0")
    default_upper = config.get("default_upper", "1e10")
    use_state_as_upper = bool(config.get("use_state_as_upper", False))

    # Special case: single state + single control → optionally use state as upper bound
    if states and len(states) == 1 and controls and len(controls) == 1 and use_state_as_upper:
        c, s = controls[0], states[0]
        return template.format(lower=default_lower, control=c, upper=f"{s}[t]")

    # General case: one complementarity per control, default bounds
    arb_eqs = [
        template.format(lower=default_lower, control=c, upper=default_upper) for c in controls
    ]
    return join_equations(arb_eqs)


# =============================================================================
# MODEL ASSEMBLY
# =============================================================================

def assemble_model(
    model_plus: Any,
    symbols: Dict[str, List[str]],
    equations: Dict[str, str],
    *,
    compile_functions: bool,
) -> Model:
    """
    Build vanilla Dolo Model from translated components.

    Creates new YAML nodes for symbols and equations,
    removes dolo_plus block, and instantiates Model.

    Args:
        model_plus: Original Dolo+ model
        symbols: Translated symbol groups
        equations: Translated equation blocks

    Returns:
        Vanilla Dolo Model
    """
    new_data = copy.deepcopy(model_plus.data)

    # Build new symbols node
    symbols_node = _build_symbols_node(symbols)

    # Build new equations node
    equations_node = _build_equations_node(equations)

    # Replace in data, removing dolo_plus block
    new_data_items = []
    for key, val in new_data.value:
        if key.value == "symbols":
            new_data_items.append((key, symbols_node))
        elif key.value == "equations":
            new_data_items.append((key, equations_node))
        elif key.value == "dolo_plus":
            continue  # Remove dolo_plus block
        else:
            new_data_items.append((key, val))

    new_data.value = new_data_items

    return Model(
        new_data,
        check=False,
        filename=model_plus._filename,
        compile_functions=compile_functions,
    )


def _build_symbols_node(symbols: Dict[str, List[str]]) -> MappingNode:
    """Build YAML MappingNode for symbols."""
    items = []
    for group, syms in symbols.items():
        key_node = ScalarNode(tag="tag:yaml.org,2002:str", value=group)
        seq_items = [
            ScalarNode(tag="tag:yaml.org,2002:str", value=s) for s in syms
        ]
        val_node = SequenceNode(tag="tag:yaml.org,2002:seq", value=seq_items)
        items.append((key_node, val_node))

    return MappingNode(tag="tag:yaml.org,2002:map", value=items)


def _build_equations_node(equations: Dict[str, str]) -> MappingNode:
    """Build YAML MappingNode for equations."""
    items = []
    for block_name, eq_str in equations.items():
        # Ensure every equation is emitted as a literal block scalar when serialized.
        # (Our importer currently asserts `style == '|'` for scalar equation payloads.)
        if isinstance(eq_str, str) and (not eq_str.endswith("\n")):
            eq_str = eq_str + "\n"
        key_node = ScalarNode(tag="tag:yaml.org,2002:str", value=block_name)
        val_node = ScalarNode(
            tag="tag:yaml.org,2002:str", value=eq_str, style="|"
        )
        items.append((key_node, val_node))

    return MappingNode(tag="tag:yaml.org,2002:map", value=items)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "doloplus_to_dolo",
    "load_mapping_tables",
    "validate_model",
    "build_context",
    "translate_symbols",
    "translate_equations",
    "synthesize_expectation",
    "assemble_model",
]
