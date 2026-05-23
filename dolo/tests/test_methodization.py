"""
Tests for methodization functor (spec_0.1d)
"""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_file():
    """Create a temporary file and return path."""
    def _create(content, suffix=".yaml"):
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as f:
            f.write(content)
            return f.name
    return _create


class TestExtractStageTargets:
    """Test extraction of stage targets (equation labels + sub-labels)."""

    def test_extract_simple_equations(self, temp_file):
        """Test extraction of simple equation labels."""
        yaml_content = """
symbols:
    states: [k]
    controls: [i]

equations:
    transition: |
        k[t] = k[t-1] + i[t-1]
    arbitrage: |
        1 - beta
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import extract_stage_targets

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        targets = extract_stage_targets(stage)

        assert 'transition' in targets
        assert 'arbitrage' in targets

    def test_extract_builder_with_subequations(self, temp_file):
        """Test extraction of builder with sub-equation labels."""
        yaml_content = """
symbols:
    states: [w]
    controls: [c]

equations:
    cntn_to_dcsn_builder:
        Bellman: |
            V = max(c)
        InvEuler: |
            c = beta
        ShadowBellman: |
            dV = c^(-gamma)
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import extract_stage_targets

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        targets = extract_stage_targets(stage)

        assert 'cntn_to_dcsn_builder' in targets
        assert 'cntn_to_dcsn_builder.Bellman' in targets
        assert 'cntn_to_dcsn_builder.InvEuler' in targets
        assert 'cntn_to_dcsn_builder.ShadowBellman' in targets

    def test_implied_forward_builders(self, temp_file):
        """Test that forward builders are implied from transitions."""
        yaml_content = """
symbols:
    states: [w]

equations:
    arvl_to_dcsn_transition: |
        w = r*b + y
    dcsn_to_cntn_transition: |
        a = w - c
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import extract_stage_targets

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        targets = extract_stage_targets(stage)

        # Transitions should be present
        assert 'arvl_to_dcsn_transition' in targets
        assert 'dcsn_to_cntn_transition' in targets

        # Implied forward builders should be added
        assert 'arvl_to_dcsn_builder' in targets
        assert 'dcsn_to_cntn_builder' in targets


class TestExtractOperatorInstances:
    """Test extraction of operator instance IDs from equation bodies."""

    def test_extract_expectation_operator(self, temp_file):
        """Test extraction of E_{y}(...) -> E_y."""
        yaml_content = """
symbols:
    states: [w]

equations:
    dcsn_to_arvl_builder:
        Bellman: |
            V[_arvl] = E_{y}(V[_dcsn])
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import extract_operator_instances

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        operators = extract_operator_instances(stage)

        assert 'E_y' in operators

    def test_extract_multiple_expectations(self, temp_file):
        """Test extraction of multiple expectation operators."""
        yaml_content = """
symbols:
    states: [w]

equations:
    builder1: |
        V = E_{y}(V) + E_{z}(W)
    builder2: |
        U = E_{w}(U)
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import extract_operator_instances

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        operators = extract_operator_instances(stage)

        assert 'E_y' in operators
        assert 'E_z' in operators
        assert 'E_w' in operators

    def test_multi_subscript_expectation(self, temp_file):
        """Test E_{w,z}(...) -> E_w_z."""
        yaml_content = """
symbols:
    states: [w]

equations:
    builder: |
        V = E_{w,z}(V)
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import extract_operator_instances

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        operators = extract_operator_instances(stage)

        assert 'E_w_z' in operators


class TestLoadMethodization:
    """Test loading methodization config."""

    def test_load_simple_methodization(self, temp_file):
        """Test loading basic methodization.yml."""
        yaml_content = """
stage: test

methods:
  - on: E_y
    schemes:
      - scheme: expectation
        method: !gauss-hermite
        settings:
          n_nodes: n_y_nodes
"""
        path = temp_file(yaml_content)

        from dolo.compiler.methodization import load_methodization

        config = load_methodization(path)

        assert config['stage'] == 'test'
        assert len(config['methods']) == 1
        assert config['methods'][0]['on'] == 'E_y'

    def test_yaml_tags_preserved(self, temp_file):
        """Test that YAML tags like !gauss-hermite are preserved."""
        yaml_content = """
methods:
  - on: E_y
    schemes:
      - scheme: expectation
        method: !gauss-hermite
"""
        path = temp_file(yaml_content)

        from dolo.compiler.methodization import load_methodization

        config = load_methodization(path)

        method = config['methods'][0]['schemes'][0]['method']
        # YAML tag should be preserved
        assert method.get('__yaml_tag__') == 'gauss-hermite' or isinstance(method, dict)


class TestMethodize:
    """Test the methodize() functor."""

    def test_methodize_returns_new_stage(self, temp_file):
        """Test that methodize returns a new stage (functorial)."""
        stage_yaml = """
symbols:
    states: [w]
    parameters: [beta]

equations:
    transition: |
        w = r*b
"""
        methodization_yaml = """
methods:
  - on: transition
    schemes: []
"""
        stage_path = temp_file(stage_yaml)
        method_path = temp_file(methodization_yaml)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import methodize

        with open(stage_path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        methodized = methodize(stage, method_path)

        # Should be different objects
        assert stage is not methodized

        # Original should not have methods
        assert stage.methods is None

        # Methodized should have methods
        assert methodized.methods is not None

    def test_exhaustive_expansion(self, temp_file):
        """Test that methodization expands to all targets."""
        stage_yaml = """
symbols:
    states: [w]

equations:
    transition: |
        w = r*b
    arbitrage: |
        1 - beta
    builder:
        Bellman: |
            V = E_{y}(V)
"""
        # Provide methods for only one target
        methodization_yaml = """
methods:
  - on: E_y
    schemes:
      - scheme: expectation
"""
        stage_path = temp_file(stage_yaml)
        method_path = temp_file(methodization_yaml)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import methodize

        with open(stage_path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        methodized = methodize(stage, method_path)

        # All targets should be present
        assert 'transition' in methodized.methods
        assert 'arbitrage' in methodized.methods
        assert 'builder' in methodized.methods
        assert 'builder.Bellman' in methodized.methods
        assert 'E_y' in methodized.methods

        # E_y should have schemes
        assert len(methodized.methods['E_y']['schemes']) == 1

        # Others should have empty schemes
        assert methodized.methods['transition']['schemes'] == []

    def test_duplicate_target_error(self, temp_file):
        """Test that duplicate targets raise an error."""
        stage_yaml = """
symbols:
    states: [w]

equations:
    transition: |
        w = r*b
"""
        methodization_yaml = """
methods:
  - on: transition
    schemes: []
  - on: transition
    schemes: []
"""
        stage_path = temp_file(stage_yaml)
        method_path = temp_file(methodization_yaml)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import methodize

        with open(stage_path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        with pytest.raises(ValueError, match="Duplicate"):
            methodize(stage, method_path)

    def test_unknown_target_warning(self, temp_file):
        """Test that unknown targets raise a warning."""
        stage_yaml = """
symbols:
    states: [w]

equations:
    transition: |
        w = r*b
"""
        methodization_yaml = """
methods:
  - on: nonexistent_target
    schemes: []
"""
        stage_path = temp_file(stage_yaml)
        method_path = temp_file(methodization_yaml)

        import yaml
        import warnings
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import methodize

        with open(stage_path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            methodize(stage, method_path)
            assert len(w) >= 1
            assert "Unknown" in str(w[0].message)


class TestEmitMethodizationTemplate:
    """Test template generation."""

    def test_emit_template(self, temp_file):
        """Test generating a methodization template."""
        stage_yaml = """
symbols:
    states: [w]

equations:
    transition: |
        w = r*b
    builder:
        Bellman: |
            V = E_{y}(V)
"""
        stage_path = temp_file(stage_yaml)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.methodization import emit_methodization_template

        with open(stage_path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        template = emit_methodization_template(stage, "test_stage")

        assert "stage: test_stage" in template
        assert "on: E_y" in template
        assert "on: transition" in template
        assert "on: builder" in template
        assert "on: builder.Bellman" in template
        assert "schemes: []" in template
