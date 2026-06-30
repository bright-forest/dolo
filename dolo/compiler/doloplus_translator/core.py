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
    build_symbol_to_native_perch,
    annotate_implicit_perch,
    state_collapse,
    lognormal_to_exp,
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

    # Step 0: Gate branching stages (parse-only, no translation yet)
    if hasattr(model_plus, 'kind') and model_plus.kind == "branching":
        raise NotImplementedError(
            f"Branching stage '{model_plus.name}' parsed successfully, "
            "but translation to vanilla dolo is not yet supported (spec 0.1l parse-only)."
        )

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

    # Symbol → native perch map (core dolo-plus rule: perch implied by group)
    symbol_to_native_perch = build_symbol_to_native_perch(symbol_groups)

    return {
        "symbol_groups": symbol_groups,
        "index_aliases": index_aliases,
        "eq_symbols": eq_symbol_map,
        "prestate_rename": prestate_rename,
        "symbol_to_native_perch": symbol_to_native_perch,
    }


def _build_prestate_rename_map(slot_map) -> Dict[str, str]:
    """
    Build mapping from prestate symbols to poststate symbols.

    Supports two slot_map formats:

    Format A (original):
        x[-1]:
            tokens: [b]
        x[+1]:
            tokens: [a]

    Format B (simplified, used in newer stage YAMLs):
        prestate: m
        poststate: a

    Args:
        slot_map: YAML node with slot definitions

    Returns:
        Dict mapping prestate names to poststate names
    """
    if slot_map is None:
        return {}

    prestate_tokens = []
    poststate_tokens = []

    # Collect all keys to detect which format we have
    keys = {k for k, _ in mapping_items(slot_map)}

    if "prestate" in keys and "poststate" in keys:
        # Format B: simple {prestate: name, poststate: name}
        for key, val in mapping_items(slot_map):
            if key == "prestate":
                prestate_tokens = [scalar_value(val)]
            elif key == "poststate":
                poststate_tokens = [scalar_value(val)]
    else:
        # Format A: x[-1]/x[+1] with nested tokens
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
    builder_map: Dict[str, Dict[str, str]] = tables.get("BUILDER_TO_BLOCK") or {}
    symbol_renames: Dict[str, str] = tables.get("SYMBOL_RENAMES") or {}

    perch_offsets: Dict[str, int] = tables.get("PERCH_TO_TIME_OFFSET") or {}

    pipelines = tables.get("PIPELINES") or {}
    transition_pipeline = pipelines.get("transitions")
    builder_pipeline = pipelines.get("builders")
    if transition_pipeline is None or builder_pipeline is None:
        raise ValueError(
            "Missing PIPELINES configuration. Expected keys: PIPELINES.transitions, PIPELINES.builders."
        )

    builder_perch_overrides = tables.get("BUILDER_PERCH_OFFSETS_OVERRIDE") or {}
    transition_perch_overrides = tables.get("TRANSITION_PERCH_OFFSETS_OVERRIDE") or {}
    state_collapse_map: Dict[str, str] = tables.get("STATE_COLLAPSE") or {}
    lognormal_map: Dict[str, str] = (tables.get("LOGNORMAL_TRANSFORM") or {}).get("symbols") or {}

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

            if step_name == "annotate_implicit_perch":
                out = annotate_implicit_perch(
                    out, context["symbol_to_native_perch"]
                )
            elif step_name == "state_collapse":
                out = state_collapse(out, state_collapse_map)
            elif step_name == "lognormal_to_exp":
                out = lognormal_to_exp(out, lognormal_map)
            elif step_name == "rename_symbols":
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
            # Per-transition perch offset overrides
            overrides = transition_perch_overrides.get(canonical, {}) or {}
            offsets_local = dict(perch_offsets)
            offsets_local.update({k: int(v) for k, v in overrides.items()})
            translated = [
                apply_pipeline(eq, transition_pipeline, perch_offsets_local=offsets_local)
                for eq in payload
            ]
            equations[block_name] = join_equations(translated)
            continue

        # Builder sub-equations (dict[subeq -> list[str]])
        if canonical in builder_map:
            if not isinstance(payload, dict):
                raise ValueError(
                    f"Expected mapping payload for builder '{label}', got {type(payload)}"
                )
            submap = builder_map[canonical] or {}
            for subeq, target_block in submap.items():
                eq_lines = payload.get(subeq)
                if not eq_lines:
                    continue
                if not isinstance(eq_lines, list):
                    raise ValueError(
                        f"Expected list payload for builder sub-equation '{label}.{subeq}', got {type(eq_lines)}"
                    )

                # Allow per-(canonical, subeq) perch-offset overrides.
                overrides = (
                    builder_perch_overrides.get(canonical, {}).get(subeq, {}) or {}
                )
                offsets_local = dict(perch_offsets)
                offsets_local.update({k: int(v) for k, v in overrides.items()})

                translated = [
                    apply_pipeline(eq, builder_pipeline, perch_offsets_local=offsets_local)
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

    # VFI synthesis: derive felicity + value from Bellman builder
    vfi_config = tables.get("VFI_SYNTHESIS")
    if vfi_config is not None:
        vfi_eqs = _synthesize_vfi_from_bellman(source_eqs, context, vfi_config)
        equations.update(vfi_eqs)

    # Composed transition: derive full transition by composing g_de with
    # prestate→state wiring (automatic state collapse: poststate → state)
    composed_config = tables.get("COMPOSED_TRANSITION")
    if composed_config is not None:
        composed_eq = _synthesize_composed_transition(
            source_eqs, context, tables, composed_config,
        )
        if composed_eq is not None:
            block = composed_config.get("block", "transition")
            equations[block] = composed_eq

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
    Synthesize Dolo expectation block from builder equations.

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
    t_ed = source_eqs.get(t_ed_config["builder"], {})
    shadow_ed = t_ed.get(t_ed_config["sub_equation"], [])

    if not shadow_ed:
        raise ValueError(
            f"Missing {t_ed_config['builder']}.{t_ed_config['sub_equation']} "
            "for expectation synthesis"
        )

    integrand_eq = shadow_ed[0]
    integrand = extract_rhs(integrand_eq)

    # Annotate implicit perch on the integrand (bare symbols → native perch)
    if config.get("annotate_implicit_perch", False):
        integrand = annotate_implicit_perch(
            integrand, context.get("symbol_to_native_perch", {})
        )

    # Shift integrand perch tags to time indices (mapping-table driven)
    shift_offsets = config.get("integrand_shift_offsets")
    if shift_offsets is None:
        raise ValueError(
            "EXPECTATION_CONFIG is missing `integrand_shift_offsets` (required)."
        )
    integrand_shifted = shift_perch_tags(
        integrand, {k: int(v) for k, v in shift_offsets.items()}
    )

    # Optionally extract multiplicative factors from T_da source
    t_da_config = config.get("T_da")
    factors_str = "1"
    if t_da_config is not None:
        t_da = source_eqs.get(t_da_config["builder"], {})
        shadow_da = t_da.get(t_da_config["sub_equation"], [])
        if not shadow_da:
            raise ValueError(
                f"Missing {t_da_config['builder']}.{t_da_config['sub_equation']} "
                "for expectation synthesis"
            )
        factor_eq = shadow_da[0]
        factors = extract_factors(factor_eq, config["exclude_pattern"])
        factors_str = " * ".join(factors) if factors else "1"

    # Build result using template
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


def _synthesize_vfi_from_bellman(
    source_eqs: Dict,
    context: Dict,
    config: Dict[str, Any],
) -> Dict[str, str]:
    """Synthesize VFI felicity and value equations from Bellman notation.

    Parses the Bellman sub-equation to extract:

    - **flow payoff** (felicity): any auxiliary definition (e.g. ``u = expr``).
      If no flow payoff is found, ``felicity = rewards_var[t] = 0``.
    - **value equation**: the structure ``V[t] = flow + discount*V[t+1]``.

    Handles two main patterns:

    1. No flow payoff::

           V = max_{ς}(E_{Ψ,θ}(V[>]))
           → felicity: u[t] = 0
           → value:    V[t] = 0 + 1.0*V[t+1]

    2. With flow payoff::

           u = (c^(1-ρ))/(1-ρ)
           V = max_{c}(u + β*V[>])
           → felicity: u[t] = (c[t])^(1-ρ)/(1-ρ)
           → value:    V[t] = u[t] + β*V[t+1]

    Config keys:

    - ``builder``: source equation label (e.g. ``cntn_to_dcsn_builder``)
    - ``sub_equation``: sub-equation key (e.g. ``Bellman``)
    - ``felicity_block``: output block name for felicity (default ``felicity``)
    - ``value_block``: output block name for value (default ``value``)
    - ``rewards_var``: felicity output variable (default ``u``)
    - ``value_var``: value function variable (default ``V``)
    """
    import re as _re

    builder_label = config["builder"]
    sub_eq = config["sub_equation"]

    builder_data = source_eqs.get(builder_label)
    if builder_data is None or not isinstance(builder_data, dict):
        return {}

    bellman_lines = builder_data.get(sub_eq, [])
    if not bellman_lines:
        return {}

    rewards_var = config.get("rewards_var", "u")
    value_var = config.get("value_var", "V")
    felicity_block = config.get("felicity_block", "felicity")
    value_block = config.get("value_block", "value")

    # ---- Identify lines ----
    flow_payoff_var = None
    flow_payoff_expr = None
    value_line = None

    for line in bellman_lines:
        line = line.strip()
        # Skip argmax lines
        if "argmax" in line:
            continue
        # Value equation: V = max_{...}(...) or V = <expr with V[>]>
        if line.startswith(f"{value_var} ") or line.startswith(f"{value_var}="):
            if "max_" in line or f"{value_var}[>]" in line or f"{value_var}[_cntn]" in line:
                value_line = line
                continue
        # Flow payoff definition: <var> = <expr> (not V, not argmax)
        if "=" in line:
            lhs = line.split("=", 1)[0].strip()
            rhs = line.split("=", 1)[1].strip()
            if lhs != value_var and lhs not in (f"{value_var}[<]", f"{value_var}[>]"):
                flow_payoff_var = lhs
                flow_payoff_expr = rhs

    if value_line is None:
        return {}

    # ---- Parse value equation ----
    # Extract inner content of max_{...}(...)
    max_match = _re.search(r"max_\{[^}]+\}\s*\((.+)\)\s*$", value_line)
    if max_match:
        inner = max_match.group(1).strip()
    else:
        inner = value_line.split("=", 1)[1].strip()

    # Strip expectation operator E_{...}(...)
    exp_match = _re.search(r"E_\{[^}]+\}\s*\((.+)\)", inner)
    if exp_match:
        inner = exp_match.group(1).strip()

    # Parse: look for V[>] term and extract discount + flow
    # Split by '+' respecting parentheses depth
    terms = _split_additive(inner)

    flow_term = None
    discount = "1.0"

    for term in terms:
        term = term.strip()
        if f"{value_var}[>]" in term or f"{value_var}[_cntn]" in term:
            # Extract discount factor (coefficient of V[>])
            disc_match = _re.match(
                rf"(\S+)\s*\*\s*{_re.escape(value_var)}\[",
                term,
            )
            if disc_match:
                discount = disc_match.group(1)
            else:
                discount = "1.0"
        elif term:
            flow_term = term

    # ---- Build equations ----
    equations: Dict[str, str] = {}

    # Felicity
    if flow_payoff_expr is not None:
        # Annotate implicit perch and convert to time [t]
        annotated = annotate_implicit_perch(
            flow_payoff_expr, context.get("symbol_to_native_perch", {})
        )
        shifted = shift_perch_tags(annotated, {"_dcsn": 0, "_cntn": 0, "_arvl": 0})
        equations[felicity_block] = f"{rewards_var}[t] = {shifted}"
    else:
        equations[felicity_block] = f"{rewards_var}[t] = 0"

    # Value
    if flow_term is not None:
        equations[value_block] = (
            f"{value_var}[t] = {flow_term}[t] + {discount}*{value_var}[t+1]"
        )
    else:
        equations[value_block] = (
            f"{value_var}[t] = 0 + {discount}*{value_var}[t+1]"
        )

    return equations


def _split_additive(expr: str) -> List[str]:
    """Split an expression by ``+`` at the top level (depth-0 only).

    Respects parentheses so that ``f(a+b) + c`` → ``["f(a+b)", "c"]``.
    """
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in expr:
        if ch in ("(", "{", "["):
            depth += 1
            current.append(ch)
        elif ch in (")", "}", "]"):
            depth -= 1
            current.append(ch)
        elif ch == "+" and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def _synthesize_composed_transition(
    source_eqs: Dict,
    context: Dict,
    tables: Dict[str, Any],
    config: Dict[str, Any],
) -> Optional[str]:
    """Synthesize a full transition by composing g_de with prestate→state wiring.

    For a standalone stage solve, the dolo transition block represents the
    full-period transition: ``next_state = f(current_state, current_control)``.
    This is derived by composing the intra-stage transition (g_de) with the
    inter-period wiring (poststate → state via the prestate/twister mapping).

    The transform pipeline applied to g_de is:

    1. ``annotate_implicit_perch`` — infer perch tags from symbol declarations
    2. ``state_collapse`` — rename poststate → state on LHS
    3. ``perch_to_time`` — with transition-convention offsets

    Config keys:

    - ``block``: output block name (default ``transition``)
    - ``source_equation``: canonical symbol of the equation to compose
      (default ``g_de``)
    - ``perch_offsets``: perch→time offsets for the composed transition
      (default ``{_dcsn: -1, _cntn: 0}``)
    """
    eq_symbols = context["eq_symbols"]
    sym_groups = context["symbol_groups"]

    source_canonical = config.get("source_equation", "g_de")

    # Find the source equation label that maps to this canonical symbol
    source_label = None
    for label, canonical in eq_symbols.items():
        if canonical == source_canonical:
            source_label = label
            break

    if source_label is None:
        return None

    payload = source_eqs.get(source_label)
    if payload is None:
        return None
    if isinstance(payload, dict):
        return None  # builders are dicts, not transitions
    if not isinstance(payload, list) or not payload:
        return None

    eq = payload[0]

    # Auto-derive state collapse: poststate → state
    # If there's one poststate and one state, the collapse is automatic.
    poststates = sym_groups.get("poststates", [])
    states = sym_groups.get("states", [])
    collapse_map = config.get("state_collapse", {})
    if not collapse_map and len(poststates) == 1 and len(states) == 1:
        collapse_map = {poststates[0]: states[0]}

    # Also merge any global STATE_COLLAPSE from tables
    global_collapse = tables.get("STATE_COLLAPSE") or {}
    merged_collapse = dict(global_collapse)
    merged_collapse.update(collapse_map)

    # Pipeline: annotate → state_collapse → lognormal (if configured) → perch_to_time
    sym_perch = context.get("symbol_to_native_perch", {})
    lognormal_map_cfg = (tables.get("LOGNORMAL_TRANSFORM") or {}).get("symbols") or {}

    out = annotate_implicit_perch(eq, sym_perch)
    if merged_collapse:
        out = state_collapse(out, merged_collapse)
    if lognormal_map_cfg:
        out = lognormal_to_exp(out, lognormal_map_cfg)

    # Perch to time with transition-convention offsets
    offsets = config.get("perch_offsets", {"_dcsn": -1, "_cntn": 0})
    offsets = {k: int(v) for k, v in offsets.items()}
    out = perch_to_time(
        out,
        sym_groups,
        context["prestate_rename"],
        offsets,
    )

    return out


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
# PREPROCESSING HELPERS
# =============================================================================

def strip_inline_comments(text: str) -> str:
    """Strip ``#`` comments from equation strings (dolang doesn't support them)."""
    lines = text.split("\n")
    return "\n".join(line.split("#")[0].rstrip() for line in lines)


def _strip_node_comments(node) -> None:
    """Strip inline ``#`` comments from a YAML ScalarNode.

    Also clears ``start_mark`` / ``end_mark`` so that dolang's
    ``parse_string`` reads from ``node.value`` instead of the
    original file buffer.
    """
    if hasattr(node, "value") and isinstance(node.value, str):
        new_val = strip_inline_comments(node.value)
        if new_val != node.value:
            node.value = new_val
            node.start_mark = None
            node.end_mark = None


def strip_equation_comments_from_data(data) -> None:
    """Walk the raw YAML AST and strip inline ``#`` comments from equations.

    Handles both scalar equations and builder sub-equation mappings.
    """
    eqs_node = mapping_get(data, "equations")
    if eqs_node is None:
        return

    for _, val in mapping_items(eqs_node):
        _strip_node_comments(val)
        # Builder sub-equations are MappingNodes with (key, val) pairs
        if hasattr(val, "value") and isinstance(val.value, list):
            for item in val.value:
                if isinstance(item, tuple) and len(item) == 2:
                    _strip_node_comments(item[1])


def extract_raw_equations(data) -> Dict:
    """Extract equations from the YAML AST as plain dicts.

    Bypasses dolang's parser entirely, which is needed when stage
    equations use informal syntax (unmarked symbols, inline comments,
    symbolic Bellman notation) that dolang cannot parse.

    Returns a dict of ``label → list[str]`` for scalar equations or
    ``label → dict[str, list[str]]`` for builder sub-equations.
    """
    eqs_node = mapping_get(data, "equations")
    if eqs_node is None:
        return {}

    result: Dict = {}
    for label, val in mapping_items(eqs_node):
        if isinstance(val, ScalarNode):
            lines = [l.strip() for l in val.value.strip().split("\n") if l.strip()]
            result[label] = lines
        elif isinstance(val, MappingNode):
            sub: Dict[str, list] = {}
            for kn, vn in val.value:
                key = kn.value if hasattr(kn, "value") else str(kn)
                lines = [l.strip() for l in vn.value.strip().split("\n") if l.strip()]
                sub[key] = lines
            result[label] = sub

    return result


# =============================================================================
# CONVENIENCE PIPELINE
# =============================================================================

def _load_source_calibration(
    calibration_source: str,
    stage_path,
) -> Dict[str, Any]:
    """Load calibration from a source YAML file.

    The path in ``calibration_source`` is resolved relative to the
    stage YAML's directory.

    Supports the dolo-plus calibration format::

        calibration:
          parameters:
            β: 0.96
            ...

    Returns a flat dict of ``{variable: value}``.
    """
    stage_dir = Path(stage_path).resolve().parent
    cal_path = stage_dir / calibration_source
    if not cal_path.exists():
        raise FileNotFoundError(
            f"Calibration source not found: {cal_path} "
            f"(resolved from CALIBRATION_SOURCE={calibration_source!r})"
        )

    with cal_path.open("r", encoding="utf-8") as f:
        cal_data = yaml.safe_load(f)

    if not isinstance(cal_data, dict):
        return {}

    # Flatten: calibration.parameters → flat dict
    result: Dict[str, Any] = {}
    cal_block = cal_data.get("calibration", cal_data)
    if isinstance(cal_block, dict):
        for section_key, section_val in cal_block.items():
            if isinstance(section_val, dict):
                result.update(section_val)
            else:
                result[section_key] = section_val
    return result


def translate_stage(
    stage_path,
    mapping_tables_source: MappingTablesSource,
    *,
    compile_functions: bool = False,
):
    """Full translation pipeline: load → strip comments → translate → assemble.

    More robust than :func:`doloplus_to_dolo` because it bypasses dolang's
    parser for equation extraction, handling informal syntax, inline
    comments, and symbolic Bellman notation.

    If the mapping tables contain ``CALIBRATION_SOURCE`` (a path relative
    to the stage YAML), the calibration file is loaded and merged into
    ``CALIBRATION_INJECT`` (source values first, then inject overrides
    on top).

    Args:
        stage_path: Path to a dolo-plus stage YAML.
        mapping_tables_source: Mapping tables (dict, YAML file path, or
            folder containing ``mapping_tables.yaml``).
        compile_functions: Whether to compile the output model functions.

    Returns:
        ``(model_dolo, tables)`` — the assembled vanilla Dolo
        :class:`Model` and the loaded mapping tables dict.
    """
    from dolo.compiler.model_import import yaml_import

    model_plus = yaml_import(str(stage_path), check=False, compile_functions=False)
    strip_equation_comments_from_data(model_plus.data)

    tables = load_mapping_tables(mapping_tables_source)
    validate_model(model_plus)

    # Load calibration from source file if specified
    cal_source = tables.get("CALIBRATION_SOURCE")
    if cal_source:
        source_cal = _load_source_calibration(cal_source, stage_path)
        # Merge: source calibration first, then CALIBRATION_INJECT overrides
        inject = tables.get("CALIBRATION_INJECT") or {}
        merged = dict(source_cal)
        merged.update(inject)
        tables["CALIBRATION_INJECT"] = merged

    perch_offsets = tables["PERCH_TO_TIME_OFFSET"]
    context = build_context(model_plus, perch_offsets)

    symbols = translate_symbols(
        context,
        keep_groups=tuple(tables["SYMBOL_GROUPS_KEEP"]),
        add_groups=tables.get("SYMBOL_GROUPS_ADD", {}) or {},
    )

    raw_eqs = extract_raw_equations(model_plus.data)
    equations = translate_equations(
        source_eqs=raw_eqs,
        context=context,
        tables=tables,
    )

    model_dolo = assemble_model(
        model_plus,
        symbols,
        equations,
        compile_functions=compile_functions,
    )

    return model_dolo, tables


def write_dolo_yaml(
    model_dolo,
    tables: Dict[str, Any],
    output_path,
    *,
    source_name: Optional[str] = None,
    mapping_name: Optional[str] = None,
    solver_target: Optional[str] = None,
) -> None:
    """Write vanilla Dolo YAML combining translator output with mapping config.

    Serialises the model (name, symbols, equations) from the translator
    and appends calibration, domain, exogenous process, and grid/options
    from the mapping tables.

    Mapping table keys consumed:

    - ``CALIBRATION_INJECT`` — dict of variable → value
    - ``DOMAIN`` — dict of state → [lb, ub]
    - ``EXOGENOUS_TYPE`` — YAML tag (e.g. ``ConstantProcess``, ``Normal``)
    - ``EXOGENOUS_PARAMS`` — dict of param → value  (supports matrices)
    - ``GRID`` — dict with ``type`` and ``orders``
    - ``CONTROLS_BOUNDS`` — dict with ``lb`` and ``ub`` lists
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    calib = tables.get("CALIBRATION_INJECT", {}) or {}
    domain = tables.get("DOMAIN", {}) or {}
    exo_type = tables.get("EXOGENOUS_TYPE", "")
    exo_params = tables.get("EXOGENOUS_PARAMS", {}) or {}
    grid = tables.get("GRID", {}) or {}
    ctrl_bounds = tables.get("CONTROLS_BOUNDS", {}) or {}

    # Extract model name, symbols, and equations from the translator output
    model_name = scalar_value(mapping_get(model_dolo.data, "name"))
    symbols_dict = dict(model_dolo.symbols)
    eq_dict: Dict[str, str] = {}
    eq_node = mapping_get(model_dolo.data, "equations")
    if eq_node is not None:
        for key, val in mapping_items(eq_node):
            eq_dict[key] = val.value if hasattr(val, "value") else str(val)

    with open(output_path, "w", encoding="utf-8") as f:
        # Header comments
        if source_name:
            f.write(f"# Auto-generated from: {source_name}\n")
        if mapping_name:
            f.write(f"# Mapping: {mapping_name}\n")
        if solver_target:
            f.write(f"# Solver target: {solver_target}\n")
        if source_name or mapping_name or solver_target:
            f.write("\n")

        # Name
        f.write(f"name: {model_name}\n")

        # Symbols
        f.write("symbols:\n")
        for group, syms in symbols_dict.items():
            f.write(f"  {group}:\n")
            for s in syms:
                f.write(f"  - {s}\n")

        # Equations — always use block scalar (|) style so dolang's
        # parse_string reads content correctly from the file buffer.
        f.write("equations:\n")
        for block, eq_str in eq_dict.items():
            eq_str = eq_str.rstrip("\n")
            f.write(f"  {block}: |\n")
            for line in eq_str.split("\n"):
                f.write(f"    {line}\n")

        # Control bounds (written as YAML sequences, not block scalars)
        if ctrl_bounds:
            lb = ctrl_bounds.get("lb", [])
            ub = ctrl_bounds.get("ub", [])
            if lb:
                f.write(f"  controls_lb:\n")
                for v in lb:
                    f.write(f"  - {v}\n")
            if ub:
                f.write(f"  controls_ub:\n")
                for v in ub:
                    f.write(f"  - {v}\n")

        # Calibration
        if calib:
            f.write("\ncalibration:\n")
            for var, val in calib.items():
                f.write(f"  {var}: {val}\n")

        # Domain
        if domain:
            f.write("\ndomain:\n")
            for var, bounds in domain.items():
                f.write(f"  {var}: {bounds}\n")

        # Exogenous process
        if exo_type:
            f.write(f"\nexogenous: !{exo_type}\n")
            for key, val in exo_params.items():
                if isinstance(val, list) and val and isinstance(val[0], list):
                    # Matrix (list of lists) — write as nested YAML
                    f.write(f"  {key}:\n")
                    for row in val:
                        f.write(f"    - [{', '.join(str(x) for x in row)}]\n")
                else:
                    f.write(f"  {key}: {val}\n")

        # Grid / options
        if grid:
            f.write("\noptions:\n")
            grid_type = grid.get("type", "Cartesian")
            f.write(f"  grid: !{grid_type}\n")
            f.write(f"    orders: {grid.get('orders', [100])}\n")


def validate_dolo_output(output_path, *, verbose: bool = True):
    """Load and validate a generated vanilla Dolo YAML file.

    Returns the compiled :class:`Model` on success, ``None`` on failure.
    """
    from dolo.compiler.model_import import yaml_import

    try:
        m = yaml_import(str(output_path), check=False, compile_functions=True)
        if verbose:
            print(f"\n  Validation: PASS")
            print(f"    Functions compiled: {list(m.functions.keys())}")
            print(f"    Exogenous: {m.exogenous}")
        grid, dp = m.discretize()
        if verbose:
            print(f"    Grid nodes: {grid['endo'].nodes.shape}")
            if hasattr(dp, "n_nodes"):
                print(f"    Exo n_nodes: {dp.n_nodes}, n_inodes: {dp.n_inodes(0)}")
        return m
    except Exception as e:
        if verbose:
            print(f"\n  Validation: FAIL")
            print(f"    Error: {e}")
            import traceback

            traceback.print_exc()
        return None


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Core pipeline
    "doloplus_to_dolo",
    "load_mapping_tables",
    "validate_model",
    "build_context",
    "translate_symbols",
    "translate_equations",
    "synthesize_expectation",
    "assemble_model",
    # Preprocessing
    "strip_equation_comments_from_data",
    "extract_raw_equations",
    # Convenience
    "translate_stage",
    "write_dolo_yaml",
    "validate_dolo_output",
]
