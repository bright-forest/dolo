from __future__ import annotations

from pathlib import Path


def test_yaml_import_plain_dolo_still_returns_model_and_compiles() -> None:
    """Regression: our clinical importer change must not affect vanilla Dolo."""

    from dolo.compiler.model import Model
    from dolo.compiler.model_import import yaml_import

    pkg_root = Path(__file__).resolve().parents[2]  # .../packages/dolo
    model_path = pkg_root / "examples" / "models" / "rbc_iid.yaml"

    model = yaml_import(str(model_path), check=True)
    assert isinstance(model, Model)

    # Touch the compilation path (recipes/factories) to ensure nothing regressed.
    assert "arbitrage" in model.functions


def test_yaml_import_doloplus_adc_stage_is_parse_only() -> None:
    """Dolo+ stage-mode: importer returns a Model, but we can keep it parse-only."""

    from dolo.compiler.model import Model
    from dolo.compiler.model_import import yaml_import

    pkg_root = Path(__file__).resolve().parents[2]  # .../packages/dolo
    stage_path = (
        pkg_root
        / "examples"
        / "models"
        / "consumption_savings_iid_egm_doloplus.yaml"
    )

    model = yaml_import(str(stage_path), check=False, compile_functions=False)
    assert isinstance(model, Model)
    assert model.filename is not None

    # Ensure we did not compile anything eagerly.
    assert getattr(model, "_Model__functions__", None) is None

    # Dolo+ stage files should still expose declared symbols/calibration, etc.
    assert "states" in model.symbols
    assert "parameters" in model.symbols

    # 0.1a requires an `equations` view (dolang+ parsing) including support for sub-equations.
    eqs = model.equations
    assert "cntn_to_dcsn_mover" in eqs
    assert isinstance(eqs["cntn_to_dcsn_mover"], dict)
    assert "Bellman" in eqs["cntn_to_dcsn_mover"]
    assert isinstance(eqs["cntn_to_dcsn_mover"]["Bellman"], list)

