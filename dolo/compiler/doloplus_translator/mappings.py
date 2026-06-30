"""
Default mappings for Dolo+ to Dolo translation.

These tables define how Dolo+ constructs map to vanilla Dolo constructs.
Users can override any of these by passing custom dicts to doloplus_to_dolo().

Mapping Categories:
    - PERCH_TO_TIME_OFFSET: perch tags → time index offsets
    - TRANSITION_TO_BLOCK: transition names → Dolo equation block names
    - SYMBOL_GROUPS_KEEP: which symbol groups pass through
    - SYMBOL_RENAMES: symbol name substitutions
    - EXPECTATION_CONFIG: how to synthesize the expectation block
"""

from typing import Dict, Tuple


# =============================================================================
# PERCH → TIME INDEX MAPPING
# =============================================================================
# Maps Dolo+ perch tags to Dolo time offsets relative to [t]
#
# Canonical named tags:   x[_arvl],  x[_dcsn],  x[_cntn]
# Preferred glyph tags:   x[<],      (unmarked), x[>]
# Arrow aliases:          x[<-],     x[-],       x[->]
#
# Glyph/arrow tags are normalized to canonical named tags upstream
# (see dolang.grammar.normalize_perch_glyphs).
#
# Dolo uses time-indexed notation:    x[t-1],   x[t],     x[t+1]

PERCH_TO_TIME_OFFSET: Dict[str, int] = {
    "_arvl": -1,   # arrival perch     → [t-1]
    "_dcsn":  0,   # decision perch    → [t]
    "_cntn": +1,   # continuation perch → [t+1]
}


# =============================================================================
# TRANSITION → EQUATION BLOCK MAPPING
# =============================================================================
# Maps Dolo+ canonical transition function names to Dolo equation block names.
# These are the defaults for EGM; override for other solvers.
#
# Dolo+ transitions:
#   g_ad : arrival → decision      (shock realization)
#   g_de : decision → continuation (direct, post-choice)
#   g_ed : continuation → decision (reverse, for EGM)

TRANSITION_TO_BLOCK: Dict[str, str] = {
    "g_ad": "half_transition",       # arrival → decision
    "g_de": "auxiliary_direct_egm",  # decision → continuation (direct)
    "g_ed": "reverse_state",         # continuation → decision (reverse)
}


# =============================================================================
# SYMBOL GROUP MAPPING
# =============================================================================
# Which Dolo+ symbol groups pass through to Dolo output.
# Groups not in this tuple are dropped during translation.

SYMBOL_GROUPS_KEEP: Tuple[str, ...] = (
    "exogenous",
    "states",
    "poststates",
    "controls",
    "parameters",
    "values_marginal",
)

# Groups typically dropped:
#   - prestate    (renamed to poststate with time shift)
#   - values      (V, not needed in EGM output)
#   - shadow_value (dV, renamed to mr)


# =============================================================================
# SYMBOL RENAMES
# =============================================================================
# Symbol name substitutions applied during translation.
# Keys are Dolo+ names, values are Dolo names.

SYMBOL_RENAMES: Dict[str, str] = {
    "dV": "mr",   # shadow value → marginal return (EGM convention)
}


# =============================================================================
# EXPECTATION SYNTHESIS CONFIG
# =============================================================================
# Specifies how to build the Dolo `expectation` block from Dolo+ builder equations.
#
# The expectation block computes: mr[t] = E[integrand * factors]
#
# Structure:
#   T_ed: source for the integrand (marginal utility at decision)
#   T_da: source for multiplicative factors (interest rate, etc.)
#   output_template: format string with {integrand} and {factors} placeholders
#   exclude_pattern: regex to exclude expectation operator when extracting factors

EXPECTATION_CONFIG: Dict = {
    # Where to find the integrand (what's inside the expectation)
    # e.g., dV[_dcsn] = (c[_dcsn])^(-γ) → integrand = (c[_dcsn])^(-γ)
    "T_ed": {
        "builder": "cntn_to_dcsn_builder",
        "sub_equation": "ShadowBellman",
    },

    # Where to find multiplicative factors (interest rate, etc.)
    # e.g., dV[_arvl] = r * E_{y}(dV[_dcsn]) → factors = [r]
    "T_da": {
        "builder": "dcsn_to_arvl_builder",
        "sub_equation": "ShadowBellman",
    },

    # Output template: {integrand} and {factors} are substituted
    "output_template": "mr[t] = ({integrand}) * {factors}",

    # Pattern to exclude when extracting factors (the E[...] term)
    "exclude_pattern": r'E_\{[^}]+\}\([^)]+\)|E_[a-zA-Z][a-zA-Z0-9_]*\([^)]+\)',
}


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "PERCH_TO_TIME_OFFSET",
    "TRANSITION_TO_BLOCK",
    "SYMBOL_GROUPS_KEEP",
    "SYMBOL_RENAMES",
    "EXPECTATION_CONFIG",
]
