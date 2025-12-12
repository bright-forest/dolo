"""
Smoke test for the "model_rep" symbol parsing (DDSL-style `symbols:` block).

This is intentionally lightweight:
- uses `yaml_import(..., check=False)` to avoid eager compilation
- asserts that nested `symbols:` collections are harvested into token lists
- asserts Backus metadata is preserved in `model.symbol_declarations` (alias of `model.__symbol_declarations__`)
"""

from __future__ import annotations

from pathlib import Path
import sys


def test_model_rep_symbols_smoke():
    from dolo import yaml_import

    dolo_root = Path(__file__).resolve().parents[2]  # packages/dolo/
    model_path = dolo_root / "examples" / "models" / "consumption_savings_iid.yaml"

    model = yaml_import(str(model_path), check=False)

    # Trigger symbol parsing
    syms = model.symbols

    for k in ("spaces", "states", "controls", "shocks", "parameters", "constraints"):
        assert k in syms

    assert set(syms["spaces"]) == {"Xa", "Xv", "Xe", "Y", "A"}
    assert set(syms["states"]) == {"w_pre", "w", "a"}
    assert syms["controls"] == ["c"]
    assert syms["shocks"] == ["y"]
    assert set(syms["parameters"]) >= {"β", "γ", "σ", "μ_w", "r", "cbar"}
    assert syms["constraints"] == ["Gamma"]

    # Prefer non-dunder alias for debugger visibility (still set from SymbolicModel.symbols)
    decls = getattr(model, "symbol_declarations", None)
    assert isinstance(decls, dict)

    assert decls["Xa"]["name"] == "arvl_state_space"
    assert decls["Xa"]["decl"].startswith("Xa @def")
    assert decls["β"]["name"] == "disc_fac"
    assert decls["Gamma"]["name"] == "feas_cons_set"
    assert decls["Gamma"]["decl"].strip() == "Gamma: Xv ->> A"


def main() -> None:
    """
    Allow running this test directly under a Python debugger (no pytest required):

        PYTHONPATH=packages/dolo python packages/dolo/dolo/tests/test_model_rep_symbols.py
        PYTHONPATH=packages/dolo python -m pdb packages/dolo/dolo/tests/test_model_rep_symbols.py
    """

    # Ensure we import the *local* Dolo code when run as a script.
    dolo_root = Path(__file__).resolve().parents[2]  # packages/dolo/
    sys.path.insert(0, str(dolo_root))

    test_model_rep_symbols_smoke()
    print("OK")


if __name__ == "__main__":
    main()

