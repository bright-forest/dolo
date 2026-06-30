"""
Tests for the operator-slot (no-schemes) methodization surface (spec 0.1d.1).

Two halves:

1. REGRESSION — the legacy ``schemes:``-list surface keeps parsing and produces
   exactly the same internal ``stage.methods`` / loaded config as before. The
   real application methodization files under ``applications/`` are used as the
   regression corpus so we lock down the production surface, not a toy.

2. NEW SURFACE — a per-named-node entry (``method: !tag`` / ``settings:`` /
   ``equations:`` / ``handler:``; no ``schemes:`` list) normalizes to the *same*
   internal representation as its legacy twin, so all downstream consumers
   (spec_factory, method_overrides) are untouched.

The internal representation is the ``schemes:``-list shape:
``{on, schemes: [{scheme, method, settings?, tool?/handler?}]}``. The new
surface is normalized into a single synthetic scheme block at load time.
"""

import warnings
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
APPS = REPO_ROOT / "applications"


@pytest.fixture
def temp_file():
    def _create(content, suffix=".yaml"):
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
            f.write(content)
            return f.name
    return _create


# ---------------------------------------------------------------------------
# Regression: every real application methodization file still loads, and its
# parsed entries keep the legacy `schemes:`-list shape.
# ---------------------------------------------------------------------------

def _all_app_methodization_files():
    if not APPS.exists():
        return []
    files = []
    for pat in ("**/methodization*.yml", "**/*_methods.yml"):
        files.extend(sorted(APPS.glob(pat)))
    # de-dup, skip anything under an `old/` directory
    seen, out = set(), []
    for f in files:
        if "old" in f.parts:
            continue
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


APP_METHODIZATION_FILES = _all_app_methodization_files()


class TestLegacyRegression:
    """Legacy `schemes:` surface keeps loading unchanged."""

    def test_corpus_nonempty(self):
        # If this fails the glob is wrong and the regression below is vacuous.
        assert len(APP_METHODIZATION_FILES) > 0

    @pytest.mark.parametrize(
        "path", APP_METHODIZATION_FILES,
        ids=[str(p.relative_to(REPO_ROOT)) for p in APP_METHODIZATION_FILES],
    )
    def test_legacy_file_loads_with_schemes_list(self, path):
        from dolo.compiler.methodization import load_methodization

        config = load_methodization(path)
        assert "methods" in config
        for entry in config["methods"]:
            assert "on" in entry
            # legacy normalization invariant: every entry carries a schemes list
            assert "schemes" in entry, (
                f"{path}: entry {entry.get('on')!r} lost its schemes list"
            )
            assert isinstance(entry["schemes"], list)
            # the legacy authoring key `method:` must NOT have leaked to the top
            # level (it belongs inside a scheme block)
            for block in entry["schemes"]:
                assert "scheme" in block or block == {}

    def test_legacy_scheme_block_unchanged(self, temp_file):
        """A legacy entry round-trips byte-for-byte in structure."""
        from dolo.compiler.methodization import load_methodization

        content = """
stage: t
methods:
  - on: E_y
    schemes:
      - scheme: expectation
        method: !gauss-hermite
        settings:
          n_nodes: n_y_nodes
"""
        config = load_methodization(temp_file(content))
        entry = config["methods"][0]
        assert entry["on"] == "E_y"
        assert len(entry["schemes"]) == 1
        block = entry["schemes"][0]
        assert block["scheme"] == "expectation"
        assert block["method"]["__yaml_tag__"] == "gauss-hermite"
        assert block["settings"] == {"n_nodes": "n_y_nodes"}


# ---------------------------------------------------------------------------
# New surface: per-named-node entry normalizes to the legacy schemes shape.
# ---------------------------------------------------------------------------

class TestNewSurfaceNormalization:

    def test_new_entry_normalizes_to_scheme_block(self, temp_file):
        from dolo.compiler.methodization import load_methodization

        # New surface: one entry per named node, `method:` at the entry level,
        # no `schemes:` list.
        content = """
stage: t
methods:
  - on: E_y
    method: !gauss-hermite
    settings:
      n_nodes: n_y_nodes
"""
        config = load_methodization(temp_file(content))
        entry = config["methods"][0]
        assert entry["on"] == "E_y"
        # normalized into a single synthetic scheme block
        assert "schemes" in entry
        assert len(entry["schemes"]) == 1
        block = entry["schemes"][0]
        assert block["method"]["__yaml_tag__"] == "gauss-hermite"
        assert block["settings"] == {"n_nodes": "n_y_nodes"}
        # scheme name derived from the node→scheme inverse map (§3)
        assert block["scheme"] == "expectation"
        # the entry-level authoring keys are consumed, not left dangling
        assert "method" not in entry
        assert "settings" not in entry

    def test_new_entry_matches_legacy_twin(self, temp_file):
        """New per-node form parses to the same internal config as legacy."""
        from dolo.compiler.methodization import load_methodization

        legacy = """
stage: t
methods:
  - on: cntn_to_dcsn_builder
    schemes:
      - scheme: bellman_backward
        method: !egm
"""
        new = """
stage: t
methods:
  - on: cntn_to_dcsn_builder
    method: !egm
"""
        cfg_legacy = load_methodization(temp_file(legacy))
        cfg_new = load_methodization(temp_file(new))
        # The single scheme block must be identical in structure.
        b_legacy = cfg_legacy["methods"][0]["schemes"][0]
        b_new = cfg_new["methods"][0]["schemes"][0]
        assert b_new["method"] == b_legacy["method"]
        assert b_new["scheme"] == b_legacy["scheme"] == "bellman_backward"

    def test_handler_aliases_tool(self, temp_file):
        """`handler:` (new) maps to the same slot the old `tool:` filled."""
        from dolo.compiler.methodization import load_methodization

        content = """
stage: t
methods:
  - on: upper_env
    method: !FUES
    handler: fues-horse
"""
        config = load_methodization(temp_file(content))
        block = config["methods"][0]["schemes"][0]
        assert block["method"]["__yaml_tag__"] == "FUES"
        # carried under `handler` (canonical) and `tool` (legacy alias) so both
        # old and new consumers can read it
        assert block.get("handler") == "fues-horse" or block.get("tool") == "fues-horse"
        assert config["methods"][0]["schemes"][0]["scheme"] == "upper_envelope"

    def test_equations_binding_preserved(self, temp_file):
        from dolo.compiler.methodization import load_methodization

        content = """
stage: t
methods:
  - on: policy
    method: !egm
    equations:
      InvEuler: InvEuler
"""
        config = load_methodization(temp_file(content))
        entry = config["methods"][0]
        block = entry["schemes"][0]
        assert block["method"]["__yaml_tag__"] == "egm"
        # the role→equation binding is carried somewhere retrievable
        assert (
            entry.get("equations") == {"InvEuler": "InvEuler"}
            or block.get("equations") == {"InvEuler": "InvEuler"}
        )

    def test_bare_node_with_no_method(self, temp_file):
        """`on:` with neither schemes nor method → empty schemes list."""
        from dolo.compiler.methodization import load_methodization

        content = """
stage: t
methods:
  - on: dcsn_to_cntn_transition
"""
        config = load_methodization(temp_file(content))
        entry = config["methods"][0]
        assert entry["schemes"] == []


# ---------------------------------------------------------------------------
# Operator-instance extraction extended to max_/argmax_ (spec 0.1f, §4.2) so
# fine-grain maximisation can attach as a named node.
# ---------------------------------------------------------------------------

class TestMaxArgmaxExtraction:

    def _stage(self, yaml_text):
        import yaml
        from dolo.compiler.model import SymbolicModel
        return SymbolicModel(yaml.compose(yaml_text))

    def test_extract_max_operator(self):
        from dolo.compiler.methodization import extract_operator_instances

        stage = self._stage("""
symbols:
    states: [w]
    controls: [c]

equations:
    cntn_to_dcsn_builder:
        Bellman: |
            V = max_{c}(u + beta*V[>])
""")
        ops = extract_operator_instances(stage)
        assert "max_c" in ops

    def test_extract_argmax_operator(self):
        from dolo.compiler.methodization import extract_operator_instances

        stage = self._stage("""
symbols:
    states: [w]
    controls: [c]

equations:
    policy:
        argmax: |
            c = argmax_{c}(u + beta*V[>])
""")
        ops = extract_operator_instances(stage)
        assert "argmax_c" in ops

    def test_expectation_still_extracted_alongside_max(self):
        from dolo.compiler.methodization import extract_operator_instances

        stage = self._stage("""
symbols:
    states: [w]
    controls: [c]

equations:
    cntn_to_dcsn_builder:
        Bellman: |
            V = max_{c}(E_{y}(V[>]))
""")
        ops = extract_operator_instances(stage)
        assert "max_c" in ops
        assert "E_y" in ops

    def test_max_target_not_warned_as_unknown(self, temp_file):
        """A methodization on max_c is a known target (no Unknown warning)."""
        import yaml
        import warnings
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import methodize

        stage_yaml = """
symbols:
    states: [w]
    controls: [c]

equations:
    cntn_to_dcsn_builder:
        Bellman: |
            V = max_{c}(u + beta*V[>])
"""
        method_yaml = """
methods:
  - on: max_c
    method: !grid-search
"""
        with open(temp_file(stage_yaml)) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            methodize(stage, temp_file(method_yaml))
            unknown = [x for x in w if "Unknown methodization target" in str(x.message)]
            assert not unknown, f"max_c wrongly flagged unknown: {[str(x.message) for x in unknown]}"


# ---------------------------------------------------------------------------
# methodize() integration: the new surface flows through the stage verb and
# produces a `stage.methods` whose entries carry the schemes list.
# ---------------------------------------------------------------------------

class TestMethodizeNewSurface:

    def test_methodize_accepts_new_surface(self, temp_file):
        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import methodize

        stage_yaml = """
symbols:
    states: [w]

equations:
    cntn_to_dcsn_builder:
        Bellman: |
            V = E_{y}(V)
"""
        method_yaml = """
methods:
  - on: E_y
    method: !gauss-hermite
"""
        with open(temp_file(stage_yaml)) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        methodized = methodize(stage, temp_file(method_yaml))
        assert "E_y" in methodized.methods
        block = methodized.methods["E_y"]["schemes"][0]
        assert block["method"]["__yaml_tag__"] == "gauss-hermite"
        assert block["scheme"] == "expectation"


class TestImpliedKernelPolicyTargets:
    """spec 0.3 / 0.1d.1: the kernel/policy method-bearing nodes that are *not*
    equation labels — ``evaluate``, ``upper_env``, and declared exogenous shocks
    — are recognised as valid methodization targets, so the migrated two-block
    examples methodize under strict validation."""

    STAGE_YAML = """name: implied_targets_stage
symbols:
  exogenous: [y]
  states: [m]
  controls: [c]
  poststates: [a]
  values: [V]
  parameters: [beta, gamma, r]
equations:
  arvl_to_dcsn_transition: |
    m = r * a[<] + y
  dcsn_to_cntn_transition: |
    a = m - c
  cntn_to_dcsn:
    value: |
      V = c**(1 - gamma) / (1 - gamma) + beta * V[>]
    marginal: |
      dV = c**(-gamma)
  policy:
    argmax: |
      c = argmax_{c}(V)
    InvEuler: |
      c[>] = (beta * dV[>])**(-1 / gamma)
"""

    def _stage(self):
        import yaml
        from dolo.compiler.model import SymbolicModel
        return SymbolicModel(yaml.compose(self.STAGE_YAML))

    def test_evaluate_implied(self):
        from dolo.compiler.methodization import extract_stage_targets
        assert "evaluate" in extract_stage_targets(self._stage())

    def test_upper_env_implied_by_policy_block(self):
        from dolo.compiler.methodization import extract_stage_targets
        assert "upper_env" in extract_stage_targets(self._stage())

    def test_declared_shock_is_a_target(self):
        from dolo.compiler.methodization import extract_stage_targets
        assert "y" in extract_stage_targets(self._stage())

    def test_strict_methodize_accepts_the_new_targets(self, temp_file):
        from dolo.compiler.stage_factory.methodize import methodize
        method_yaml = (
            "methods:\n"
            "  - on: policy\n"
            "    method: !egm\n"
            "  - on: evaluate\n"
            "    method: !Cartesian\n"
            "  - on: upper_env\n"
            "    method: !FUES\n"
            "  - on: y\n"
        )
        # Must not raise "Unknown methodization target" under strict validation.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            methodize(self._stage(), temp_file(method_yaml, suffix=".yml"), strict=True)
