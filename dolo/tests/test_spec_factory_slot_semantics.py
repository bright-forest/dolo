"""v3 slot semantics for spec_factory (kikku-runspec-v3)."""

import pytest
import yaml

from dolo.compiler.spec_factory import SpecFactoryError, load, make


def _write_recipe(registry, recipe_dict):
    path = registry / "spec_factory.yaml"
    path.write_text(yaml.dump(recipe_dict))
    return str(path)


def _minimal_registry(tmp_path):
    """calibration/main, settings/default, stages/st/methods.yml."""
    cal_dir = tmp_path / "calibration"
    cal_dir.mkdir()
    (cal_dir / "main.yaml").write_text(
        yaml.dump({"calibration": {"beta": 0.96, "gamma": 2.0, "R": 1.045}})
    )
    (cal_dir / "cal_x.yaml").write_text(
        yaml.dump({"calibration": {"beta": 0.9}})
    )
    (cal_dir / "cal_y.yaml").write_text(
        yaml.dump({"calibration": {"gamma": 0.3}})
    )
    sett_dir = tmp_path / "settings"
    sett_dir.mkdir()
    (sett_dir / "default.yaml").write_text(
        yaml.dump({"settings": {"n_a": 200, "tol": 1e-8}})
    )
    st = tmp_path / "stages" / "st"
    st.mkdir(parents=True)
    (st / "methods.yml").write_text(
        yaml.dump({"methods": [{"on": "E_y", "schemes": []}]})
    )
    return tmp_path


class TestSlotSemanticsV3:
    def test_multi_address_broadcast(self, tmp_path):
        """Same $draw at two calibration chains; stray keys merge everywhere."""
        reg = _minimal_registry(tmp_path)
        path = _write_recipe(reg, {"stages": {
            "stage_x": {
                "calibration": {"all": ["calibration/cal_x", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/st/methods"]},
            },
            "stage_y": {
                "calibration": {"all": ["calibration/cal_y", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/st/methods"]},
            },
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            draw={"beta": 0.96, "orphan": 99},
        )
        assert dict(spec["stage_x"][0]["calibration"])["beta"] == 0.96
        assert dict(spec["stage_x"][0]["calibration"])["orphan"] == 99
        assert dict(spec["stage_y"][0]["calibration"])["gamma"] == 0.3
        assert dict(spec["stage_y"][0]["calibration"])["beta"] == 0.96
        assert dict(spec["stage_y"][0]["calibration"])["orphan"] == 99

    def test_methods_addition_new_builder(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        mdir = tmp_path / "stages" / "mm"
        mdir.mkdir(parents=True)
        (mdir / "base.yml").write_text(yaml.dump({
            "methods": [
                {"on": "old_builder", "schemes": [{"scheme": "s1", "method": "A"}]},
            ]
        }))
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/mm/base", "$ms"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            ms={
                "methods": [
                    {
                        "on": "new_builder",
                        "schemes": [{"scheme": "sn", "method": "Z"}],
                    }
                ]
            },
        )
        methods = spec["st"][0]["methods"]["methods"]
        ons = [e["on"] for e in methods]
        assert "old_builder" in ons
        assert "new_builder" in ons

    def test_methods_partial_scheme_merge_preserves_fields(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        mdir = tmp_path / "stages" / "mm"
        mdir.mkdir(parents=True)
        (mdir / "base.yml").write_text(yaml.dump({
            "methods": [
                {
                    "on": "builder",
                    "schemes": [
                        {
                            "scheme": "upper_envelope",
                            "method": "FUES",
                            "settings": {"m_bar": 1},
                            "grid": {"n": 50},
                        },
                    ],
                },
            ]
        }))
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/mm/base", "$ms"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            ms={
                "methods": [
                    {
                        "on": "builder",
                        "schemes": [{"scheme": "upper_envelope", "method": "NEGM"}],
                    }
                ]
            },
        )
        sch = spec["st"][0]["methods"]["methods"][0]["schemes"][0]
        assert sch["method"] == "NEGM"
        assert sch["settings"] == {"m_bar": 1}
        assert sch["grid"] == {"n": 50}

    def test_methods_new_scheme_appended(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        mdir = tmp_path / "stages" / "mm"
        mdir.mkdir(parents=True)
        (mdir / "base.yml").write_text(yaml.dump({
            "methods": [
                {
                    "on": "builder",
                    "schemes": [{"scheme": "bellman_backward", "method": "EGM"}],
                },
            ]
        }))
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/mm/base", "$ms"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            ms={
                "methods": [
                    {
                        "on": "builder",
                        "schemes": [{"scheme": "upper_envelope", "method": "FUES"}],
                    }
                ]
            },
        )
        schemes = spec["st"][0]["methods"]["methods"][0]["schemes"]
        names = [s["scheme"] for s in schemes]
        assert names == ["bellman_backward", "upper_envelope"]

    def test_undeclared_slot_raises(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/st/methods"]},
            }
        }})
        recipe = load(path)
        with pytest.raises(SpecFactoryError, match="undeclared"):
            make(recipe, registry_dir=str(reg), not_a_slot={"x": 1})

    def test_empty_bindings_noop(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/st/methods"]},
            }
        }})
        recipe = load(path)
        spec1 = make(recipe, registry_dir=str(reg))
        spec2 = make(recipe, registry_dir=str(reg), draw={})
        assert dict(spec1["st"][0]["calibration"]) == dict(spec2["st"][0]["calibration"])

    def test_tier_wrapped_slot_merges_per_dimension(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default", "$draw"]},
                "methods": {"all": ["stages/st/methods"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            draw={"calibration": {"beta": 0.91}, "settings": {"n_a": 500}},
        )
        assert dict(spec["st"][0]["calibration"])["beta"] == 0.91
        assert dict(spec["st"][0]["settings"])["n_a"] == 500

    def test_tier_wrapped_methods_list_merges_correctly(self, tmp_path):
        """Tier-wrapped slot with `methods` a bare list: list-wrap in _build_chain.

        _merge_chain is dict-only; the methods dimension must receive
        {"methods": [...]} so the list is not dropped (spec §4.1 amendment).
        """
        reg = _minimal_registry(tmp_path)
        mdir = tmp_path / "stages" / "mm"
        mdir.mkdir(parents=True)
        (mdir / "base.yml").write_text(yaml.dump({
            "methods": [
                {"on": "old_builder", "schemes": [{"scheme": "s1", "method": "A"}]},
            ]
        }))
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main", "$m_switch"]},
                "settings": {"all": ["settings/default", "$m_switch"]},
                "methods": {"all": ["stages/mm/base", "$m_switch"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            m_switch={
                "calibration": {"aux": 7},
                "methods": [
                    {
                        "on": "new_builder",
                        "schemes": [{"scheme": "sn", "method": "Z"}],
                    }
                ],
            },
        )
        cal = dict(spec["st"][0]["calibration"])
        assert cal.get("aux") == 7
        methods = spec["st"][0]["methods"]["methods"]
        ons = [e["on"] for e in methods]
        assert "old_builder" in ons
        assert "new_builder" in ons

    def test_typo_key_silent_in_calibration(self, tmp_path):
        reg = _minimal_registry(tmp_path)
        path = _write_recipe(reg, {"stages": {
            "st": {
                "calibration": {"all": ["calibration/main", "$draw"]},
                "settings": {"all": ["settings/default"]},
                "methods": {"all": ["stages/st/methods"]},
            }
        }})
        recipe = load(path)
        spec = make(
            recipe,
            registry_dir=str(reg),
            draw={"beta": 0.91, "betaa": 0.97},
        )
        cal = dict(spec["st"][0]["calibration"])
        assert cal["beta"] == 0.91
        assert cal["betaa"] == 0.97
