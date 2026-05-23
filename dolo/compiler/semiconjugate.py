"""
Semiconjugate Transformation for ADC Stages

This module implements the Stachurski semiconjugacy transformation that converts
a Bellman operator from S = E ∘ max to Ŝ = max ∘ E form.

Mathematical Foundation (Iterates Lemma):
-----------------------------------------
Let (V, S) and (V̂, Ŝ) be order semiconjugate under F, G, meaning:
    S = G ∘ F   and   Ŝ = F ∘ G

Then for all n ≥ 1:
    S^n = G ∘ Ŝ^{n-1} ∘ F
    Ŝ^n = F ∘ S^{n-1} ∘ G

The Key Transformation:
-----------------------
Original (S = E ∘ max):
    V[_arvl] = E_y[ max_c{ u(c) + β*V'[_arvl] } ]
    The expectation is OUTSIDE the maximization.
    
    In ADC:
        cntn_to_dcsn_builder: V[_dcsn] = max_c{ u(c) + β*V[_cntn] }
        dcsn_to_arvl_builder: V[_arvl] = E_y(V[_dcsn])

Conjugate (Ŝ = max ∘ E):
    V[_arvl] = max_c{ u(c) + β*E_y[V'[_arvl]] }
    The expectation is INSIDE the maximization.
    
    In ADC:
        cntn_to_dcsn_builder: V[_dcsn] = max_c{ u(c) + β*E_y(V[_cntn]) }
        dcsn_to_arvl_builder: V[_arvl] = V[_dcsn]  (identity)

The transformation moves the expectation INSIDE the decision problem.
The agent optimizes over a SMOOTH continuation value.

References:
-----------
- semiconjugacy-iterates.tex (AI/prompts/03012025/final-report/source-reports/)
- Stachurski & Sargent, DP2, Chapter on Transforms
- Ma, Stachurski & Toda (2022), Q-Transform paper
"""

import copy
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field


@dataclass
class SemiconjugateTransform:
    """
    Result of a semiconjugate transformation.
    
    Attributes:
        original_stage: The input stage (unmodified)
        conjugate_stage: The transformed stage
        F_map: Description of the F transformation (V → E[V])
        G_map: Description of the G transformation (Ṽ → max{u + βṼ})
    """
    original_stage: Any
    conjugate_stage: Any
    F_map: str
    G_map: str


def _extract_expectation_operator(builder_eq: str) -> Optional[Tuple[str, str]]:
    """
    Extract expectation operator from a builder equation.
    
    E.g., "V[_arvl] = E_{y}(V[_dcsn])" -> ("E_{y}", "y")
    
    Returns:
        (operator_string, shock_name) or None
    """
    # Match E_{y}(...) or E_y(...)
    match = re.search(r'(E_\{?(\w+)\}?)\s*\(', builder_eq)
    if match:
        return (match.group(1), match.group(2))
    return None


def _remove_expectation_from_builder(builder_eq: str) -> str:
    """
    Remove expectation from a builder equation, making it identity.
    
    E.g., "V[_arvl] = E_{y}(V[_dcsn])" -> "V[_arvl] = V[_dcsn]"
    """
    # Remove E_{y}(...) keeping the inside
    result = re.sub(r'E_\{\w+\}\s*\(([^)]+)\)', r'\1', builder_eq)
    result = re.sub(r'E_\w+\s*\(([^)]+)\)', r'\1', result)
    # Remove orphaned "r *" (from shadow value)
    result = re.sub(r'^\s*r\s*\*\s*', '', result.strip())
    return result.strip()


def _add_expectation_to_continuation(decision_eq: str, operator: str) -> str:
    """
    Add expectation operator around continuation value in decision equation.
    
    E.g., "V[_dcsn] = max_{c}(u(c) + β*V[_cntn])"
       -> "V[_dcsn] = max_{c}(u(c) + β*E_{y}(V[_cntn]))"
    """
    # Find V[_cntn] or V[+1] etc. and wrap with expectation
    # Pattern: β*V[_cntn] or β * V[_cntn]
    result = re.sub(
        r'(\bβ\s*\*\s*)(V\[[^\]]+\])',
        rf'\1{operator}(\2)',
        decision_eq
    )
    
    # Also handle dV for shadow value
    result = re.sub(
        r'(\bβ\s*\*\s*)(dV\[[^\]]+\])',
        rf'\1{operator}(\2)',
        result
    )
    
    return result


def conjugate_transform(stage: Any) -> SemiconjugateTransform:
    """
    Apply the semiconjugate (conjugate Bellman) transformation to a stage.
    
    This transforms the Bellman operator from:
        Original (S = E ∘ max): expectation OUTSIDE the max
    to:
        Conjugate (Ŝ = max ∘ E): expectation INSIDE the max
    
    Key transformations:
        1. cntn_to_dcsn_builder: Add E_y around continuation value V[_cntn]
        2. dcsn_to_arvl_builder: Remove E_y (becomes identity)
    
    Args:
        stage: A SymbolicModel or dict with ADC structure
            
    Returns:
        SemiconjugateTransform containing both original and conjugate stages
        
    Raises:
        ValueError: If stage is not in ADC format or has unsupported structure
    """
    # Deep copy the stage to avoid modifying original
    if hasattr(stage, 'data'):
        conjugate_data = copy.deepcopy(stage.data)
        original_data = stage.data
    elif isinstance(stage, dict):
        conjugate_data = copy.deepcopy(stage)
        original_data = stage
    else:
        raise ValueError("Stage must be a dict or have a .data attribute")
    
    # Get equations
    equations = conjugate_data.get('equations', {})
    original_equations = original_data.get('equations', {})
    
    # ==========================================================================
    # STEP 1: Extract expectation operator from dcsn_to_arvl_builder
    # ==========================================================================
    dcsn_to_arvl = original_equations.get('dcsn_to_arvl_builder', {})
    operator = "E_{y}"  # default
    shock_name = "y"
    
    if isinstance(dcsn_to_arvl, dict):
        bellman = dcsn_to_arvl.get('Bellman', '')
        if isinstance(bellman, str):
            extracted = _extract_expectation_operator(bellman)
            if extracted:
                operator, shock_name = extracted
    
    # ==========================================================================
    # STEP 2: Add expectation INSIDE the decision (cntn_to_dcsn_builder)
    # ==========================================================================
    if 'cntn_to_dcsn_builder' in equations:
        builder = equations['cntn_to_dcsn_builder']
        if isinstance(builder, dict):
            for key in ['Bellman', 'InvEuler', 'ShadowBellman']:
                if key in builder and isinstance(builder[key], str):
                    # Only add to Bellman and InvEuler (where continuation appears)
                    if key in ['Bellman', 'InvEuler']:
                        builder[key] = _add_expectation_to_continuation(
                            builder[key], operator
                        )
    
    # ==========================================================================
    # STEP 3: Remove expectation from dcsn_to_arvl_builder (becomes identity)
    # ==========================================================================
    if 'dcsn_to_arvl_builder' in equations:
        builder = equations['dcsn_to_arvl_builder']
        if isinstance(builder, dict):
            for key in list(builder.keys()):
                if isinstance(builder[key], str):
                    builder[key] = _remove_expectation_from_builder(builder[key])
    
    # ==========================================================================
    # STEP 4: Update dolo_plus metadata
    # ==========================================================================
    dolo_plus = conjugate_data.get('dolo_plus', {})
    
    # Update dialect
    if 'dialect' in dolo_plus:
        dolo_plus['dialect'] = 'adc-stage-conjugate'
    
    # Update operator metadata
    if 'operators' in dolo_plus:
        for op_name, op_info in dolo_plus['operators'].items():
            if isinstance(op_info, dict):
                op_info['default_location'] = 'dcsn'
                op_info['position'] = 'inside_decision'
    
    # Add semiconjugacy metadata
    dolo_plus['semiconjugacy'] = {
        'relation': 'conjugate',
        'original_operator': 'S = E_y ∘ max_c',
        'conjugate_operator': 'Ŝ = max_c ∘ E_y',
        'transformation': 'Expectation moved from dcsn_to_arvl_builder INSIDE cntn_to_dcsn_builder',
        'F_map': f'Ṽ(a) = E_{shock_name}[V(g(a,{shock_name}))]',
        'G_map': 'V(w) = max_c{u(c) + β*Ṽ(w-c)}',
        'iterates_lemma': 'S^n = G ∘ Ŝ^{n-1} ∘ F',
    }
    
    # Create result
    return SemiconjugateTransform(
        original_stage=stage,
        conjugate_stage=conjugate_data,
        F_map=f"Ṽ(a) = E_{shock_name}[V(g(a,{shock_name}))]",
        G_map="V(w) = max_c{u(c) + β*Ṽ(w-c)}",
    )


def to_conjugate(stage):
    """
    Shorthand for conjugate_transform(stage).conjugate_stage
    
    Args:
        stage: A stage dict or SymbolicModel
        
    Returns:
        The conjugate stage (dict or same type as input)
    """
    return conjugate_transform(stage).conjugate_stage


def print_transformation_summary(transform: SemiconjugateTransform):
    """Print a readable summary of the transformation."""
    print("=" * 70)
    print("SEMICONJUGATE TRANSFORMATION SUMMARY")
    print("=" * 70)
    
    print("\n--- The Key Insight ---")
    print("""
The expectation moves INSIDE the decision problem:

Original (S = E ∘ max):
    V = E_y[ max_c{ u(c) + β*V' } ]
        ^^^^
        Expectation is OUTSIDE the max
    
    In ADC:
        cntn_to_dcsn_builder: V[_dcsn] = max_c{ u(c) + β*V[_cntn] }
        dcsn_to_arvl_builder: V[_arvl] = E_y(V[_dcsn])  ← expectation here

Conjugate (Ŝ = max ∘ E):
    V = max_c{ u(c) + β*E_y[V'] }
                      ^^^^
        Expectation is INSIDE the max (in continuation value)
    
    In ADC:
        cntn_to_dcsn_builder: V[_dcsn] = max_c{ u(c) + β*E_y(V[_cntn]) }
                                                     ^^^^
                                          Expectation moved HERE
        dcsn_to_arvl_builder: V[_arvl] = V[_dcsn]  (identity)
""")
    
    print("--- Why This Matters ---")
    print("""
The agent optimizes over a SMOOTH continuation value:

1. First compute Ṽ(a) = E_y[V'(g(a,y))] for all continuation states
2. Then solve: max_c{ u(c) + β*Ṽ(w-c) }

The max is over a differentiable function, enabling:
- Faster convergence (no discontinuities from max over shocks)
- Better numerical stability
- Natural fit with EGM (endogenous grid method)
""")
    
    print("--- Semiconjugacy Maps ---")
    print(f"F: {transform.F_map}")
    print(f"G: {transform.G_map}")
    
    print("\n--- Iterates Lemma ---")
    print("S^n = G ∘ Ŝ^{n-1} ∘ F")
    print("(Iterate in conjugate space, then transform back)")
    print("=" * 70)
