"""
Pure functions for equation string transformations.

All functions in this module are stateless and take explicit parameters.
They transform equation strings from Dolo+ notation to Dolo notation.

Key transformations:
    - perch_to_time: Convert perch tags to time indices
    - shift_to_next_period: Shift variables forward one period
    - rename_symbols: Apply symbol name substitutions
    - extract_rhs: Get right-hand side of an equation
    - extract_factors: Get multiplicative factors from an expression
"""

import re
from typing import Dict, List, Optional, Set


# =============================================================================
# PERCH → TIME CONVERSION
# =============================================================================

def perch_to_time(
    equation: str,
    symbol_groups: Dict[str, List[str]],
    prestate_rename: Dict[str, str],
    perch_offsets: Dict[str, int],
) -> str:
    """
    Convert perch-indexed notation to time-indexed notation.

    Transforms:
        x[_arvl] → x[t-1]
        x[_dcsn] → x[t]
        x[_cntn] → x[t+1]

    Special handling:
        - Prestates are renamed and shifted: b[_arvl] → a[t-1]
        - Poststates at continuation stay at [t]: a[_cntn] → a[t]

    Args:
        equation: Equation string with perch tags
        symbol_groups: Dict mapping group names to symbol lists
        prestate_rename: Dict mapping prestate names to poststate names
        perch_offsets: Dict mapping perch tags to time offsets

    Returns:
        Equation string with time indices
    """
    poststates: Set[str] = set(symbol_groups.get("poststates", []))
    prestates: Set[str] = set(prestate_rename.keys())

    pattern = r'(\w+)\[(_arvl|_dcsn|_cntn)\]'

    def replace_tag(match: re.Match) -> str:
        name, tag = match.groups()
        offset = perch_offsets.get(tag, 0)

        # Prestate: rename and use offset
        if name in prestates:
            new_name = prestate_rename[name]
            return _format_time_index(new_name, -1)

        # Poststate at continuation: stays at [t]
        if name in poststates and tag == "_cntn":
            return _format_time_index(name, 0)

        # Default: apply offset from mapping
        return _format_time_index(name, offset)

    return re.sub(pattern, replace_tag, equation)


def shift_to_next_period(
    equation: str,
    perch_offsets: Optional[Dict[str, int]] = None,
) -> str:
    """
    Shift perch-tagged variables forward one period.

    Used for expectation integrands: the integrand is evaluated
    at the next period's decision perch.

    Transforms:
        x[_arvl] → x[t]    (arrival becomes current)
        x[_dcsn] → x[t+1]  (decision becomes next)
        x[_cntn] → x[t+1]  (continuation becomes next)

    Args:
        equation: Equation string with perch tags
        perch_offsets: Dict mapping perch tags to time offsets

    Returns:
        Equation string with shifted time indices
    """
    # Back-compat wrapper around the configurable shifter.
    offsets = perch_offsets or {"_arvl": 0, "_dcsn": 1, "_cntn": 1}
    return shift_perch_tags(equation, offsets)


def shift_perch_tags(equation: str, offsets: Dict[str, int]) -> str:
    """
    Replace perch tags with time indices using explicit offsets.

    This is intentionally *dumber* than `perch_to_time`: it does not rename
    prestates and does not special-case poststates. It simply rewrites the
    bracket tags:

      [_arvl] → [t+offsets[_arvl]]
      [_dcsn] → [t+offsets[_dcsn]]
      [_cntn] → [t+offsets[_cntn]]
    """
    pattern = r"\[(_arvl|_dcsn|_cntn)\]"

    def replace_tag(match: re.Match) -> str:
        tag = match.group(1)
        if tag not in offsets:
            return match.group(0)
        offset = int(offsets[tag])
        if offset == 0:
            return "[t]"
        if offset > 0:
            return f"[t+{offset}]"
        return f"[t{offset}]"

    return re.sub(pattern, replace_tag, equation)


def _format_time_index(name: str, offset: int) -> str:
    """Format a symbol with time index."""
    if offset == 0:
        return f"{name}[t]"
    elif offset > 0:
        return f"{name}[t+{offset}]"
    else:
        return f"{name}[t{offset}]"


# =============================================================================
# SYMBOL MANIPULATION
# =============================================================================

def rename_symbols(equation: str, renames: Dict[str, str]) -> str:
    """
    Apply symbol name substitutions.

    Args:
        equation: Equation string
        renames: Dict mapping old names to new names

    Returns:
        Equation with renamed symbols

    Example:
        >>> rename_symbols("dV[_dcsn] = u'(c)", {"dV": "mr"})
        "mr[_dcsn] = u'(c)"
    """
    result = equation
    for old_name, new_name in renames.items():
        # Match whole word only
        pattern = rf'\b{re.escape(old_name)}\b'
        result = re.sub(pattern, new_name, result)
    return result


def remove_discount_factor(equation: str, discount_symbol: str = "β") -> str:
    """
    Remove discount factor from equation.

    Dolo's mr convention already includes β, so we strip it
    from translated equations to avoid double-counting.

    Args:
        equation: Equation string
        discount_symbol: Symbol for discount factor (default: β)

    Returns:
        Equation with discount factor removed

    Example:
        >>> remove_discount_factor("(β) * (mr[t])")
        "(mr[t])"
    """
    # Pattern variations: (β) * x, β * x, (β)*x
    patterns = [
        rf'\({re.escape(discount_symbol)}\)\s*\*\s*\(',
        rf'\({re.escape(discount_symbol)}\)\s*\*\s*',
        rf'{re.escape(discount_symbol)}\s*\*\s*',
    ]

    result = equation
    for pattern in patterns:
        result = re.sub(pattern, '(', result, count=1)
        if result != equation:
            break

    return result


# =============================================================================
# EQUATION PARSING
# =============================================================================

def extract_rhs(equation: str) -> str:
    """
    Extract the right-hand side of an equation.

    Args:
        equation: Equation string (may or may not contain '=')

    Returns:
        Right-hand side, or entire string if no '='

    Example:
        >>> extract_rhs("dV[_dcsn] = (c[_dcsn])^(-γ)")
        "(c[_dcsn])^(-γ)"
    """
    if "=" not in equation:
        return equation.strip()
    return equation.split("=", 1)[1].strip()


def extract_lhs(equation: str) -> str:
    """
    Extract the left-hand side of an equation.

    Args:
        equation: Equation string

    Returns:
        Left-hand side, or empty string if no '='
    """
    if "=" not in equation:
        return ""
    return equation.split("=", 1)[0].strip()


def extract_factors(
    equation: str,
    exclude_pattern: str,
) -> List[str]:
    """
    Extract multiplicative factors from an expression.

    Splits on '*' and filters out terms matching the exclude pattern.
    Used to extract factors like interest rate 'r' while excluding
    the expectation operator E[...].

    Args:
        equation: Equation string (typically RHS of an equation)
        exclude_pattern: Regex pattern for terms to exclude

    Returns:
        List of factor strings

    Example:
        >>> extract_factors("r * E_{y}(dV)", r"E_.*\\(.*\\)")
        ["r"]
    """
    rhs = extract_rhs(equation)

    # Remove excluded terms
    cleaned = re.sub(exclude_pattern, '', rhs)

    # Split on multiplication
    parts = cleaned.split('*')

    # Filter and clean
    factors = []
    for part in parts:
        stripped = part.strip()
        # Skip empty or parentheses-only
        if stripped and stripped not in ('', '()', '( )'):
            factors.append(stripped)

    return factors


# =============================================================================
# EQUATION JOINING
# =============================================================================

def join_equations(equations: List[str]) -> str:
    """
    Join multiple equations with newlines.

    Args:
        equations: List of equation strings

    Returns:
        Single string with equations separated by newlines
    """
    return "\n".join(equations)


def transform_equations(
    equations: List[str],
    symbol_groups: Dict[str, List[str]],
    prestate_rename: Dict[str, str],
    perch_offsets: Dict[str, int],
) -> str:
    """
    Transform a list of equations from perch to time notation.

    Convenience function combining perch_to_time and join_equations.

    Args:
        equations: List of equation strings with perch tags
        symbol_groups: Dict mapping group names to symbol lists
        prestate_rename: Dict mapping prestate names to poststate names
        perch_offsets: Dict mapping perch tags to time offsets

    Returns:
        Single string with transformed equations
    """
    transformed = [
        perch_to_time(eq, symbol_groups, prestate_rename, perch_offsets)
        for eq in equations
    ]
    return join_equations(transformed)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "perch_to_time",
    "shift_to_next_period",
    "shift_perch_tags",
    "rename_symbols",
    "remove_discount_factor",
    "extract_rhs",
    "extract_lhs",
    "extract_factors",
    "join_equations",
    "transform_equations",
]
