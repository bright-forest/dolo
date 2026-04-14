"""Unit tests for spec_factory (spec 0.1s)."""

import pytest
import yaml

from dolo.compiler.spec_factory import load, make, SpecGraph, Recipe, SpecFactoryError


@pytest.fixture
def registry(tmp_path):
    """Create a minimal test registry."""
    cal_dir = tmp_path / "calibration"
    cal_dir.mkdir()
    (cal_dir / "main.yaml").write_text(yaml.dump({
        "calibration": {"beta": 0.96, "gamma": 2.0, "R": 1.045}
    }))
    (cal_dir / "overlay.yaml").write_text(yaml.dump({
        "calibration": {"beta": 0.99}
    }))

    sett_dir = tmp_path / "settings"
    sett_dir.mkdir()
    (sett_dir / "default.yaml").write_text(yaml.dump({
        "settings": {"n_a": 200, "tol": 1e-8}
    }))

    stage_dir = tmp_path / "stages" / "stage_a"
    stage_dir.mkdir(parents=True)
    (stage_dir / "stage_a_methods.yml").write_text(yaml.dump({
        "methods": [{"on": "E_y", "schemes": []}]
    }))

    stage_b_dir = tmp_path / "stages" / "stage_b"
    stage_b_dir.mkdir(parents=True)
    (stage_b_dir / "stage_b_methods.yml").write_text(yaml.dump({
        "methods": [{"on": "mover", "schemes": [{"scheme": "upper_envelope", "method": "FUES"}]}]
    }))

    return tmp_path


def _write_recipe(registry, recipe_dict):
    """Write a spec_factory YAML and return its path."""
    path = registry / "spec_factory.yaml"
    path.write_text(yaml.dump(recipe_dict))
    return str(path)


# ── Phase A: load() tests ──────────────────────────────────────────────

class TestLoad:
    def test_load_minimal(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        assert isinstance(recipe, Recipe)
        assert "stage_a" in recipe.stages
        assert recipe["stage_a"].calibration["all"] == ["calibration/main"]

    def test_load_detects_slots(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods", "$method_switch"]},
            }
        }})
        recipe = load(path)
        assert "draw" in recipe.slots
        assert "method_switch" in recipe.slots
        assert recipe.list_slots() == ["draw", "method_switch"]

    def test_load_period_ranges(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {
                    "all": ["calibration/main"],
                    "45-59": ["calibration/overlay"],
                },
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        assert "45-59" in recipe["stage_a"].calibration

    def test_load_rejects_overlapping_ranges(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {
                    "all": ["calibration/main"],
                    "0-30": ["calibration/overlay"],
                    "20-59": ["calibration/overlay"],
                },
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        with pytest.raises(SpecFactoryError, match="Overlapping"):
            load(path)

    def test_load_rejects_dotdot(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["../escape"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        with pytest.raises(SpecFactoryError, match="\\.\\."):
            load(path)

    def test_load_missing_all_key(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"0-30": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        with pytest.raises(SpecFactoryError, match="Missing 'all'"):
            load(path)

    def test_load_with_periods(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "periods": [10, 50],
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        assert recipe["stage_a"].periods == (10, 50)

    def test_list_sources(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        sources = recipe.list_sources()
        assert "calibration/main" in sources
        assert "$draw" not in sources


# ── Phase B: make() + SpecGraph tests ──────────────────────────────────

class TestMake:
    def test_make_base_spec(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        assert isinstance(spec, SpecGraph)
        assert spec["stage_a"][0]["calibration"]["beta"] == 0.96
        assert spec["stage_a"][0]["settings"]["n_a"] == 200

    def test_make_with_draw_slot(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry), draw={"beta": 0.99})
        assert spec["stage_a"][0]["calibration"]["beta"] == 0.99
        assert spec["stage_a"][0]["calibration"]["gamma"] == 2.0

    def test_make_unfilled_slot_is_noop(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        assert spec["stage_a"][0]["calibration"]["beta"] == 0.96

    def test_make_right_biased_merge(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "calibration/overlay"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        assert spec["stage_a"][0]["calibration"]["beta"] == 0.99
        assert spec["stage_a"][0]["calibration"]["gamma"] == 2.0

    def test_specgraph_immutable(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        with pytest.raises(TypeError):
            spec["stage_a"][0]["calibration"]["beta"] = 999

    def test_specgraph_stage_not_found(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        with pytest.raises(KeyError, match="stage_x"):
            spec["stage_x"]

    def test_specgraph_inactive_period(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "periods": [10, 50],
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        assert spec.is_active("stage_a", 30)
        assert not spec.is_active("stage_a", 5)
        with pytest.raises(KeyError):
            spec["stage_a"][5]["calibration"]

    def test_make_source_not_found(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/nonexistent"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        with pytest.raises(SpecFactoryError, match="not found"):
            make(recipe, registry_dir=str(registry))

    def test_make_warns_unused_slot(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        with pytest.warns(UserWarning, match="not declared"):
            make(recipe, registry_dir=str(registry), phantom={"x": 1})

    def test_specgraph_period_range_lookup(self, registry):
        (registry / "calibration" / "retired.yaml").write_text(
            yaml.dump({"calibration": {"beta": 0.80}})
        )
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {
                    "all": ["calibration/main"],
                    "45-59": ["calibration/retired"],
                },
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        assert spec["stage_a"][30]["calibration"]["beta"] == 0.96
        assert spec["stage_a"][50]["calibration"]["beta"] == 0.80
        assert spec["stage_a"][50]["calibration"]["gamma"] == 2.0


# ── Phase C: Consumer API tests ───────────────────────────────────────

class TestConsumerAPI:
    def test_specgraph_has_stage_names(self, registry):
        """SpecGraph must have stage_names for adapter detection."""
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        assert hasattr(spec, "stage_names")
        assert "stage_a" in spec.stage_names


class TestSlotTierChecking:
    def test_rejects_mixed_tier_slot(self, registry):
        """Flat slot dict mixing calibration + settings keys must raise."""
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        with pytest.raises(SpecFactoryError, match="Mixed tiers"):
            make(recipe, registry_dir=str(registry),
                 draw={"beta": 0.95, "n_a": 200})

    def test_pure_calibration_slot_ok(self, registry):
        """Flat slot dict with only calibration keys must work."""
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry),
                     draw={"beta": 0.95, "gamma": 3.0})
        assert spec["stage_a"][0]["calibration"]["beta"] == 0.95

    def test_tier_wrapped_slot_bypasses_check(self, registry):
        """Explicitly wrapped slot dict must not trigger tier check."""
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry),
                     draw={"calibration": {"beta": 0.95},
                           "settings": {"n_a": 500}})
        assert spec["stage_a"][0]["calibration"]["beta"] == 0.95


class TestSpecFactoryFixes:
    def test_method_switch_tuple_key(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_b": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_b/stage_b_methods", "$method_switch"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(registry),
            method_switch={
                ("stage_b", "mover", "upper_envelope"): "NEGM",
            },
        )
        patched = spec["stage_b"][0]["methods"]["methods"][0]["schemes"][0]["method"]
        assert patched["__yaml_tag__"] == "NEGM"

    def test_method_switch_bad_form_raises(self, registry):
        path = _write_recipe(registry, {"stages": {
            "stage_b": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_b/stage_b_methods", "$method_switch"]},
            }
        }})
        recipe = load(path)
        with pytest.raises(SpecFactoryError, match="tuple keys"):
            make(
                recipe,
                registry_dir=str(registry),
                method_switch={"upper_envelope": "NEGM"},
            )

    def test_parent_chain_resolution(self, registry):
        (registry / "calibration" / "main_parent.yaml").write_text(yaml.dump({
            "calibration": {"beta": 0.96, "gamma": 2.0}
        }))
        (registry / "calibration" / "child.yaml").write_text(yaml.dump({
            "parent": "calibration/main_parent",
            "calibration": {"beta": 0.99},
        }))
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/child"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        cal = spec["stage_a"][0]["calibration"]
        assert cal["beta"] == 0.99
        assert cal["gamma"] == 2.0
        assert "parent" not in cal

    def test_parent_cycle_raises(self, registry):
        (registry / "calibration" / "cycle_a.yaml").write_text(yaml.dump({
            "parent": "calibration/cycle_b",
            "calibration": {"beta": 0.97},
        }))
        (registry / "calibration" / "cycle_b.yaml").write_text(yaml.dump({
            "parent": "calibration/cycle_a",
            "calibration": {"gamma": 2.1},
        }))
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/cycle_a"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        with pytest.raises(SpecFactoryError, match="cycle"):
            make(recipe, registry_dir=str(registry))

    def test_parent_deep_chain_raises(self, registry):
        for i in range(12):
            payload = {"calibration": {f"k_{i}": i}}
            if i > 0:
                payload["parent"] = f"calibration/deep_{i-1}"
            (registry / "calibration" / f"deep_{i}.yaml").write_text(yaml.dump(payload))
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/deep_11"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        with pytest.raises(SpecFactoryError, match="depth exceeded 10"):
            make(recipe, registry_dir=str(registry))

    def test_specgraph_deep_immutable(self, registry):
        (registry / "calibration" / "with_list.yaml").write_text(yaml.dump({
            "calibration": {"beta": 0.96, "lambdas": [0.1, 0.2]},
        }))
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/with_list"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        lambdas = spec["stage_a"][0]["calibration"]["lambdas"]
        assert isinstance(lambdas, tuple)
        with pytest.raises(AttributeError):
            lambdas.append(999)

    def test_methods_file_overlay_preserves_unrelated_targets(self, registry):
        stage_dir = registry / "stages" / "stage_merge"
        stage_dir.mkdir(parents=True)
        (stage_dir / "methods_base.yml").write_text(yaml.dump({
            "methods": [
                {
                    "on": "E_y",
                    "schemes": [{"scheme": "expectation", "method": "gauss-hermite"}],
                },
                {
                    "on": "cntn_to_dcsn_mover",
                    "schemes": [{"scheme": "upper_envelope", "method": "FUES"}],
                },
            ]
        }))
        (stage_dir / "methods_overlay.yml").write_text(yaml.dump({
            "methods": [
                {
                    "on": "cntn_to_dcsn_mover",
                    "schemes": [{"scheme": "upper_envelope", "method": "NEGM"}],
                }
            ]
        }))
        path = _write_recipe(registry, {"stages": {
            "stage_merge": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {
                    "all": [
                        "stages/stage_merge/methods_base",
                        "stages/stage_merge/methods_overlay",
                    ]
                },
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        methods = spec["stage_merge"][0]["methods"]["methods"]
        targets = {entry["on"]: entry for entry in methods}
        assert "E_y" in targets
        assert "cntn_to_dcsn_mover" in targets
        mover_scheme = targets["cntn_to_dcsn_mover"]["schemes"][0]
        assert mover_scheme["scheme"] == "upper_envelope"
        assert mover_scheme["method"] == "NEGM"

    def test_source_file_strips_metadata_keys(self, registry):
        (registry / "calibration" / "meta_parent.yaml").write_text(yaml.dump({
            "calibration": {"beta": 0.96, "gamma": 2.0}
        }))
        (registry / "calibration" / "meta_child.yaml").write_text(yaml.dump({
            "parent": "calibration/meta_parent",
            "description": "tmp note",
            "version": 1,
            "__comment__": "ignore",
            "calibration": {"beta": 0.91},
        }))
        path = _write_recipe(registry, {"stages": {
            "stage_a": {
                "calibration": {"all": ["calibration/meta_child"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/stage_a/stage_a_methods"]},
            }
        }})
        recipe = load(path)
        spec = make(recipe, registry_dir=str(registry))
        cal = spec["stage_a"][0]["calibration"]
        assert cal["beta"] == 0.91
        assert cal["gamma"] == 2.0
        assert "description" not in cal
        assert "version" not in cal
        assert "__comment__" not in cal
        assert "parent" not in cal
