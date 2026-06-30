"""
Tests for the kernel/policy two-block stage surface + legacy desugaring
(spec 0.3 — kernel/policy schema; Phase 4 parser).

The mathematics (spec 0.3 §0, §2):

  legacy single backward builder, max IN the value equation
      cntn_to_dcsn_opr:
        Bellman:  V = max_{c}( (c^(1-γ))/(1-γ) + β*V[>] )
        InvEuler: c[>] = (β*dV[>])^(-1/γ)
        MarginalBellman: dV = (c)^(-γ)

  desugars (denotationally identical, no model re-meant) to the two-block form:
      cntn_to_dcsn:            # evaluation block, NO max
        value:    V  = (c^(1-γ))/(1-γ) + β*V[>]
        marginal: dV = (c)^(-γ)
      policy:                  # constructs σ; carries the method
        argmax:   c = argmax_{c}( (c^(1-γ))/(1-γ) + β*V[>] )
        InvEuler: c[>] = (β*dV[>])^(-1/γ)

Two halves:

1. PARSE — both surfaces parse (the new two-block form and the legacy
   single-builder form). This is the regression: legacy keeps parsing.
2. DESUGAR — the legacy single-builder form desugars to the same two-block
   view as a model authored directly in the two-block form. The `max` is
   *lifted*, never dropped.
"""

import tempfile

import pytest


@pytest.fixture
def load_stage():
    def _load(yaml_text):
        import yaml
        from dolo.compiler.model import SymbolicModel
        return SymbolicModel(yaml.compose(yaml_text))
    return _load


# Worked example (spec 0.3 §2), consumption-savings IID.
LEGACY_SINGLE_BUILDER = """
symbols:
    states: [w]
    controls: [c]
    parameters: [beta, gamma, r]

equations:
    cntn_to_dcsn_opr:
        Bellman: |
            V = max_{c}((c^(1-gamma))/(1-gamma) + beta*V[>])
        InvEuler: |
            c[>] = (beta*dV[>])^(-1/gamma)
        MarginalBellman: |
            dV = (c)^(-gamma)
    dcsn_to_arvl_opr:
        Bellman: |
            V[<] = E_{y}(V)
        MarginalBellman: |
            dV[<] = r*E_{y}(dV)
"""

NEW_TWO_BLOCK = """
symbols:
    states: [w]
    controls: [c]
    parameters: [beta, gamma, r]

equations:
    cntn_to_dcsn:
        value: |
            V = (c^(1-gamma))/(1-gamma) + beta*V[>]
        marginal: |
            dV = (c)^(-gamma)
    dcsn_to_arvl:
        value: |
            V[<] = E_{y}(V)
        marginal: |
            dV[<] = r*E_{y}(dV)
    policy:
        InvEuler: |
            c[>] = (beta*dV[>])^(-1/gamma)
"""


class TestBothSurfacesParse:
    """Regression: legacy keeps parsing; new form parses too."""

    def test_legacy_single_builder_parses(self, load_stage):
        stage = load_stage(LEGACY_SINGLE_BUILDER)
        eqs = stage.equations
        assert "cntn_to_dcsn_opr" in eqs
        # the max is still present in the authored value line (not silently dropped)
        bellman = eqs["cntn_to_dcsn_opr"]["Bellman"][0]
        assert "max_{c}" in bellman

    def test_new_two_block_parses(self, load_stage):
        stage = load_stage(NEW_TWO_BLOCK)
        eqs = stage.equations
        assert "cntn_to_dcsn" in eqs
        assert "policy" in eqs
        assert "value" in eqs["cntn_to_dcsn"]
        assert "marginal" in eqs["cntn_to_dcsn"]
        # evaluation block carries NO max
        assert "max_" not in eqs["cntn_to_dcsn"]["value"][0]


class TestDesugar:
    """The legacy single-builder form desugars to the two-block view."""

    def test_desugar_lifts_max_into_policy(self, load_stage):
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        stage = load_stage(LEGACY_SINGLE_BUILDER)
        view = desugar_kernel_policy(stage.equations)

        # evaluation block present, named by the canonical kernel/policy name
        assert "cntn_to_dcsn" in view
        evalblk = view["cntn_to_dcsn"]
        assert "value" in evalblk
        # the value line is the inner objective — max lifted OUT
        value_line = evalblk["value"][0]
        assert "max_" not in value_line
        assert "argmax" not in value_line
        # the inner objective survives intact
        assert "beta" in value_line and "V[_cntn]" in value_line

    def test_desugar_synthesizes_policy_argmax(self, load_stage):
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        stage = load_stage(LEGACY_SINGLE_BUILDER)
        view = desugar_kernel_policy(stage.equations)

        assert "policy" in view
        policy = view["policy"]
        # an argmax line constructing the control
        assert "argmax" in policy
        argmax_line = policy["argmax"][0]
        assert "argmax_{c}" in argmax_line
        # the InvEuler line moved into the policy block (it constructs σ)
        assert "InvEuler" in policy

    def test_desugar_preserves_marginal(self, load_stage):
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        stage = load_stage(LEGACY_SINGLE_BUILDER)
        view = desugar_kernel_policy(stage.equations)
        # MarginalBellman becomes the evaluation block's `marginal` role
        evalblk = view["cntn_to_dcsn"]
        assert "marginal" in evalblk
        assert "(c[_dcsn])^(-(gamma))" in evalblk["marginal"][0]

    def test_new_form_is_idempotent_under_desugar(self, load_stage):
        """A model already in the two-block form is unchanged by desugaring."""
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        stage = load_stage(NEW_TWO_BLOCK)
        view = desugar_kernel_policy(stage.equations)

        assert "cntn_to_dcsn" in view
        assert "policy" in view
        # value/marginal unchanged
        assert view["cntn_to_dcsn"]["value"] == stage.equations["cntn_to_dcsn"]["value"]
        assert view["cntn_to_dcsn"]["marginal"] == stage.equations["cntn_to_dcsn"]["marginal"]
        # no max introduced or left behind
        assert "max_" not in view["cntn_to_dcsn"]["value"][0]

    def test_desugar_arrival_block_renamed(self, load_stage):
        """dcsn_to_arvl_opr (no max) desugars to the dcsn_to_arvl evaluation block."""
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        stage = load_stage(LEGACY_SINGLE_BUILDER)
        view = desugar_kernel_policy(stage.equations)

        assert "dcsn_to_arvl" in view
        arr = view["dcsn_to_arvl"]
        assert "value" in arr
        # the arrival expectation is preserved
        assert "E_{y}" in arr["value"][0]
        # arrival block has no policy (no control to choose)
        assert "argmax" not in arr


# Real-world shape (cons-port port_stage): the Bellman block carries BOTH the
# max value line AND an explicit author-written argmax line.
LEGACY_EXPLICIT_ARGMAX = """
symbols:
    states: [k]
    controls: [s]
    parameters: [beta]

equations:
    cntn_to_dcsn_builder:
        Bellman: |
            V = max_{s}(E_{z}(V[>]))
            s = argmax_{s}(E_{z}(V[>]))
"""


class TestExplicitArgmaxRouting:
    """An author-written argmax line must land in `policy`, never in `value`."""

    def test_argmax_line_routed_to_policy(self, load_stage):
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        view = desugar_kernel_policy(load_stage(LEGACY_EXPLICIT_ARGMAX).equations)

        # evaluation block: value carries ONLY the (max-lifted) value equation
        evalblk = view["cntn_to_dcsn"]
        for line in evalblk["value"]:
            assert "argmax" not in line, f"argmax leaked into evaluation value: {line}"
            assert "max_" not in line
        assert len(evalblk["value"]) == 1

        # policy block: exactly one argmax for s (no duplicate from the lifted max)
        argmax_lines = view["policy"]["argmax"]
        s_argmaxes = [l for l in argmax_lines if "argmax_{s}" in l]
        assert len(s_argmaxes) == 1, f"expected one argmax for s, got {argmax_lines}"


class TestDenotationalEquivalence:
    """The desugared legacy view matches a directly-authored two-block view."""

    def test_legacy_desugar_matches_new_evaluation_block(self, load_stage):
        from dolo.compiler.stage_factory.symbolic import desugar_kernel_policy

        legacy_view = desugar_kernel_policy(load_stage(LEGACY_SINGLE_BUILDER).equations)
        new_view = desugar_kernel_policy(load_stage(NEW_TWO_BLOCK).equations)

        # The evaluation block (value + marginal) must be equation-for-equation
        # identical between the desugared legacy form and the native two-block
        # form — that is what "denotationally identical" means at the surface.
        assert legacy_view["cntn_to_dcsn"]["value"] == new_view["cntn_to_dcsn"]["value"]
        assert legacy_view["cntn_to_dcsn"]["marginal"] == new_view["cntn_to_dcsn"]["marginal"]
        assert legacy_view["dcsn_to_arvl"]["value"] == new_view["dcsn_to_arvl"]["value"]
        # the InvEuler in the policy block matches
        assert legacy_view["policy"]["InvEuler"] == new_view["policy"]["InvEuler"]
