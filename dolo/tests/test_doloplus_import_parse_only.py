from __future__ import annotations

from pathlib import Path

import yaml
import pytest


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

    if not stage_path.exists():
        pytest.skip(f"Test fixture not found: {stage_path}")

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


# =====================================================================
# spec_0.1l — Branching stage parsing
# =====================================================================

STAGES_DIR = (
    Path(__file__).resolve().parents[2]
    / "examples" / "models" / "doloplus"
    / "retirement_choice_doloplus" / "stages"
)


def _load_stage(name: str):
    """Helper: load a SymbolicModel from stage YAML."""
    from dolo.compiler.model import SymbolicModel

    path = STAGES_DIR / f"{name}.yaml"
    with open(path, "r") as f:
        return SymbolicModel(yaml.compose(f.read()), filename=str(path))


def test_branching_stage_kind() -> None:
    """Branching stage has kind='branching'."""
    model = _load_stage("worker_decision")
    assert model.kind == "branching"


def test_branching_stage_branch_control() -> None:
    """Branching stage has branch_control='agent'."""
    model = _load_stage("worker_decision")
    assert model.branch_control == "agent"


def test_branching_stage_branch_labels() -> None:
    """Branch labels follow YAML declaration order."""
    model = _load_stage("worker_decision")
    assert model.branch_labels == ["work", "retire"]


def test_branching_stage_branch_poststates() -> None:
    """Branch poststates have correct structure."""
    model = _load_stage("worker_decision")
    bp = model.branch_poststates
    assert bp is not None
    assert set(bp.keys()) == {"work", "retire"}
    assert "a" in bp["work"]
    assert "a_ret" in bp["retire"]


def test_branching_stage_flat_poststates() -> None:
    """Flat poststates is disjoint union of branch poststate names."""
    model = _load_stage("worker_decision")
    flat_ps = model.symbols["poststates"]
    assert "a" in flat_ps
    assert "a_ret" in flat_ps


def test_branching_stage_branch_transitions() -> None:
    """Branch transitions parsed for each branch label."""
    model = _load_stage("worker_decision")
    bt = model.branch_transitions
    assert bt is not None
    assert set(bt.keys()) == {"work", "retire"}
    # Each branch has at least one equation
    assert len(bt["work"]) >= 1
    assert len(bt["retire"]) >= 1


def test_branching_stage_branch_values() -> None:
    """Branch-keyed values (V_cntn) parsed correctly."""
    model = _load_stage("worker_decision")
    bv = model.branch_values
    assert bv is not None
    assert "V_cntn" in bv
    assert set(bv["V_cntn"].keys()) == {"work", "retire"}


def test_branching_stage_equations() -> None:
    """All equation groups parse successfully for branching stage."""
    model = _load_stage("worker_decision")
    eqs = model.equations
    assert "arvl_to_dcsn_transition" in eqs
    assert "dcsn_to_cntn_transition" in eqs
    assert "cntn_to_dcsn_mover" in eqs
    assert "dcsn_to_arvl_mover" in eqs


def test_non_branching_stage_no_branch_attrs() -> None:
    """Non-branching stages don't have branch attributes (symbol-level)."""
    model = _load_stage("worker_consumption")
    assert model.kind is None
    assert model.branch_labels is None
    assert model.branch_poststates is None
    assert model.branch_values is None
    # Note: branch_transitions triggers .equations which requires dolo_plus.dialect
    # for nested sub-equations. Non-branching stages without dialect can't parse
    # sub-equations, so we check the attribute directly.
    assert not hasattr(model, '_branch_transitions')


def test_values_marginal_recognized() -> None:
    """values_marginal is recognized as a symbol group."""
    model = _load_stage("worker_consumption")
    assert "values_marginal" in model.symbols
    assert len(model.symbols["values_marginal"]) > 0


def test_overlapping_poststate_names_raises() -> None:
    """Overlapping poststate names across branches should raise ValueError."""
    from dolo.compiler.model import SymbolicModel

    # Construct YAML with overlapping poststate names
    yaml_str = """
name: BadBranching
kind: branching
branch_control: agent
symbols:
  states:
    x: "@in R+"
  poststates:
    work:
      a: "@in R+"
    retire:
      a: "@in R+"
  controls:
    d: "@in {work, retire}"
  parameters: [delta]
equations:
  arvl_to_dcsn_transition: |
    x = x[<]
  dcsn_to_cntn_transition:
    work: |
      a[>] = x
    retire: |
      a[>] = x
  cntn_to_dcsn_mover:
    Bellman: |
      x = x
  dcsn_to_arvl_mover:
    Bellman: |
      x[<] = x
"""
    data = yaml.compose(yaml_str)
    model = SymbolicModel(data)
    with pytest.raises(ValueError, match="Poststate.*appears in multiple branches"):
        _ = model.symbols










