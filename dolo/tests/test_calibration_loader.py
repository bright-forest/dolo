"""
Tests for calibration and settings loaders (spec_0.1c).
"""

import pytest
import tempfile
import os


@pytest.fixture
def temp_file():
    """Fixture to create and clean up temp files."""
    files = []

    def _create(content, suffix='.yaml'):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        files.append(path)
        return path

    yield _create

    for path in files:
        if os.path.exists(path):
            os.unlink(path)


class TestLoadCalibration:
    def test_load_from_dict(self):
        from dolo.compiler.calibration import load_calibration

        calib = load_calibration({'beta': 0.96, 'delta': 0.1})
        assert calib['beta'] == 0.96
        assert calib['delta'] == 0.1

    def test_load_from_file(self, temp_file):
        from dolo.compiler.calibration import load_calibration

        path = temp_file("beta: 0.96\ndelta: 0.1")
        calib = load_calibration(path)
        assert calib['beta'] == 0.96

    def test_load_nested_calibration_key(self):
        from dolo.compiler.calibration import load_calibration

        data = {'calibration': {'parameters': {'beta': 0.96}}}
        calib = load_calibration(data)
        assert calib['beta'] == 0.96

    def test_load_split_format_extracts_parameters(self):
        from dolo.compiler.calibration import load_calibration

        data = {
            'parameters': {'beta': 0.96},
            'settings': {'n_w': 200}
        }
        calib = load_calibration(data)
        assert calib['beta'] == 0.96
        assert 'n_w' not in calib


class TestLoadSettings:
    def test_load_from_dict(self):
        from dolo.compiler.calibration import load_settings

        settings = load_settings({'n_w': 200, 'tol': 1e-8})
        assert settings['n_w'] == 200

    def test_load_nested_settings_key(self):
        from dolo.compiler.calibration import load_settings

        data = {'settings': {'n_w': 200, 'tol': 1e-8}}
        settings = load_settings(data)
        assert settings['n_w'] == 200

    def test_load_from_split_calibration_file(self):
        from dolo.compiler.calibration import load_settings

        data = {
            'calibration': {
                'parameters': {'beta': 0.96},
                'settings': {'n_w': 200}
            }
        }
        settings = load_settings(data)
        assert settings['n_w'] == 200


class TestCalibrate:
    def test_calibrate_returns_new_stage(self, temp_file):
        """Test calibrate() returns a new stage with .calibration attached."""
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
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.calibration import calibrate

        # Load as SymbolicModel (syntactic stage)
        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        # Original has no calibration
        assert stage.calibration is None

        # Calibrate returns a NEW stage
        calibrated = calibrate(stage, {'beta': 0.96, 'delta': 0.1})

        # New stage has calibration attached
        assert calibrated.calibration is not None
        assert calibrated.calibration['beta'] == pytest.approx(0.96)
        assert calibrated.calibration['delta'] == pytest.approx(0.1)

        # Original stage unchanged (functorial)
        assert stage.calibration is None
        assert stage is not calibrated


class TestConfigure:
    def test_configure_returns_new_stage(self, temp_file):
        """Test configure() returns a new stage with .settings attached."""
        yaml_content = """
name: test_model

symbols:
    states: [k]
    controls: [i]
    parameters: [beta]
    settings: [n_k, tol]

equations:
    transition: |
        k[t] = k[t-1] + i[t-1]
    arbitrage: |
        1 - beta   | -inf <= i[t] <= inf
"""
        path = temp_file(yaml_content)

        import yaml
        from dolo.compiler.model import SymbolicModel
        from dolo.compiler.calibration import calibrate, configure

        with open(path) as f:
            stage = SymbolicModel(yaml.compose(f.read()))

        # Calibrate first
        calibrated = calibrate(stage, {'beta': 0.96})

        # Original has no settings
        assert calibrated.settings is None

        # Configure returns a NEW stage
        configured = configure(calibrated, {'n_k': 100, 'tol': 1e-8})

        # New stage has settings attached
        assert configured.settings is not None
        assert configured.settings['n_k'] == 100
        assert configured.settings['tol'] == pytest.approx(1e-8)

        # Calibration preserved
        assert configured.calibration['beta'] == pytest.approx(0.96)

        # Previous stage unchanged
        assert calibrated.settings is None
