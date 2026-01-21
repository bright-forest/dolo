"""
Tests for decorated symbol support (spec_0.1c).

Tests that:
1. Legacy list format still works
2. Decorated mapping format is parsed
3. symbols_math contains Lark ASTs for decorators
"""

import pytest
import tempfile
import os


@pytest.fixture
def temp_yaml_file():
    """Fixture to create and clean up temp YAML files."""
    files = []

    def _create(content):
        fd, path = tempfile.mkstemp(suffix='.yaml')
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        files.append(path)
        return path

    yield _create

    for path in files:
        if os.path.exists(path):
            os.unlink(path)


def test_legacy_symbols_format(temp_yaml_file):
    """Legacy list format continues to work unchanged."""
    yaml_content = """
name: test_model
model_type: dtcc

symbols:
    exogenous: [e]
    states: [k]
    controls: [i]
    parameters: [beta, delta]

equations:
    transition: |
        k[t] = (1-delta)*k[t-1] + i[t-1] + e[t]
    arbitrage: |
        1 - beta*(1-delta)   | -inf <= i[t] <= inf

calibration:
    beta: 0.96
    delta: 0.1
    k: 1.0
    i: 0.1
    e: 0.0
"""
    path = temp_yaml_file(yaml_content)
    from dolo import yaml_import
    model = yaml_import(path)

    # Legacy symbols still work
    assert 'parameters' in model.symbols
    assert model.symbols['parameters'] == ['beta', 'delta']
    assert model.symbols['states'] == ['k']
    assert model.symbols['controls'] == ['i']

    # symbols_math should be empty for legacy format
    assert model.symbols_math == {}


def test_decorated_symbols_format(temp_yaml_file):
    """Decorated mapping format is parsed and stored in symbols_math."""
    yaml_content = """
name: test_decorated
model_type: dtcc

symbols:
    exogenous: [e]
    states: [k]
    controls: [i]
    parameters:
        beta: "@in (0,1)"
        delta: "@in R+"

equations:
    transition: |
        k[t] = (1-delta)*k[t-1] + i[t-1] + e[t]
    arbitrage: |
        1 - beta*(1-delta)   | -inf <= i[t] <= inf

calibration:
    beta: 0.96
    delta: 0.1
    k: 1.0
    i: 0.1
    e: 0.0
"""
    path = temp_yaml_file(yaml_content)
    from dolo import yaml_import
    model = yaml_import(path)

    # Legacy names-only view still works
    assert 'parameters' in model.symbols
    assert model.symbols['parameters'] == ['beta', 'delta']

    # symbols_math should have the parsed decorators
    assert 'parameters' in model.symbols_math
    assert 'beta' in model.symbols_math['parameters']
    assert 'delta' in model.symbols_math['parameters']

    # Check the AST structure
    beta_tree = model.symbols_math['parameters']['beta']
    assert beta_tree is not None
    assert beta_tree.data == 'start'

def test_mixed_symbols_format(temp_yaml_file):
    """Mix of legacy list and decorated mapping formats."""
    yaml_content = """
name: test_mixed
model_type: dtcc

symbols:
    exogenous: [e]
    states: [k]
    controls: [i]
    parameters:
        beta: "@in (0,1)"
        delta: "@in R+"

equations:
    transition: |
        k[t] = (1-delta)*k[t-1] + i[t-1] + e[t]
    arbitrage: |
        1 - beta*(1-delta)   | -inf <= i[t] <= inf

calibration:
    beta: 0.96
    delta: 0.1
    k: 1.0
    i: 0.1
    e: 0.0
"""
    path = temp_yaml_file(yaml_content)
    from dolo import yaml_import
    model = yaml_import(path)

    # Legacy list format
    assert model.symbols['states'] == ['k']
    assert model.symbols['exogenous'] == ['e']

    # Decorated mapping format
    assert model.symbols['parameters'] == ['beta', 'delta']
    assert 'parameters' in model.symbols_math
    assert 'beta' in model.symbols_math['parameters']

    # states should not be in symbols_math (list format)
    assert 'states' not in model.symbols_math


def test_decorator_primitives(temp_yaml_file):
    """Test various primitive domain decorators parse correctly."""
    yaml_content = """
name: test_primitives
model_type: dtcc

symbols:
    exogenous: [e]
    states: [k]
    controls: [i]
    parameters:
        a: "@in R"
        b: "@in R+"
        c_param: "@in R++"
        n: "@in Z+"

equations:
    transition: |
        k[t] = a*k[t-1] + i[t-1] + e[t]
    arbitrage: |
        1 - b   | -inf <= i[t] <= inf

calibration:
    a: 0.9
    b: 1.0
    c_param: 0.5
    n: 10
    k: 1.0
    i: 0.1
    e: 0.0
"""
    path = temp_yaml_file(yaml_content)
    from dolo import yaml_import
    model = yaml_import(path)

    assert model.symbols['parameters'] == ['a', 'b', 'c_param', 'n']

    # All should have ASTs
    for name in ['a', 'b', 'c_param', 'n']:
        assert name in model.symbols_math['parameters']
        assert model.symbols_math['parameters'][name] is not None


def test_ordering_preserved(temp_yaml_file):
    """YAML insertion order is preserved for mapping-valued symbol groups."""
    yaml_content = """
name: test_order
model_type: dtcc

symbols:
    exogenous: [e]
    states: [k]
    controls: [i]
    parameters:
        gamma: "@in R+"
        beta: "@in (0,1)"
        alpha: "@in R"

equations:
    transition: |
        k[t] = alpha*k[t-1] + i[t-1] + e[t]
    arbitrage: |
        1 - beta*gamma   | -inf <= i[t] <= inf

calibration:
    gamma: 2.0
    beta: 0.96
    alpha: 0.3
    k: 1.0
    i: 0.1
    e: 0.0
"""
    path = temp_yaml_file(yaml_content)
    from dolo import yaml_import
    model = yaml_import(path)

    # Order should match YAML insertion order, not alphabetical
    assert model.symbols['parameters'] == ['gamma', 'beta', 'alpha']
