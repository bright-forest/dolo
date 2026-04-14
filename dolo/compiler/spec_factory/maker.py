"""Spec factory resolution engine (spec 0.1s).

Resolves a Recipe into an immutable SpecGraph by loading source
files from the registry, substituting slot bindings, and running
the sequential merge per (stage, dimension, period-group).
"""

from __future__ import annotations

import copy
import re
import warnings
from pathlib import Path
from typing import Optional

import yaml

from .graph import SpecGraph
from .loader import SpecFactoryError


_DIMENSIONS = ("calibration", "settings", "methods")
_KNOWN_SOURCE_METADATA_KEYS = {"parent", "description", "version", "__comment__"}


def _resolve_source_path(name, registry_dir):
    """Resolve a source name to a file path. Try .yaml then .yml."""
    base = registry_dir / name
    for ext in (".yaml", ".yml"):
        candidate = Path(str(base) + ext)
        if candidate.exists():
            return candidate
    if base.exists():
        return base
    raise SpecFactoryError(
        f"Source file not found: '{name}'\n"
        f"  x Tried: {base}.yaml, {base}.yml\n"
        f"  i Check that the source name is correct and the file exists in the registry."
    )


def _deep_merge_dicts(base, overlay):
    """Recursively right-bias merge two dicts."""
    result = copy.deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(overlay, dict):
        return result
    for key, value in overlay.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_source_file_raw(path):
    """Load a YAML source file without resolving parent chains.

    Uses tag-tolerant loading for files with custom YAML tags
    (!egm, !max, etc.) — detected by .yml extension or _methods
    in the filename (convention: methods files use these tags).
    """
    from dolo.compiler.methodization import load_methodization

    path_str = str(path)
    if path_str.endswith('.yml') or '_methods' in path_str:
        data = load_methodization(path)
        if data is None:
            return {}
        return copy.deepcopy(data) if isinstance(data, dict) else {}

    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return dict(data)


def _load_source_file_with_parent(path, registry_dir, visited=None, depth=0):
    """Load source YAML and resolve parent chains without dimension unwrapping."""
    if depth > 10:
        raise SpecFactoryError(
            f"Parent chain depth exceeded 10 while loading '{path}'"
        )
    resolved_path = path.resolve()
    if visited is None:
        visited = set()
    if resolved_path in visited:
        raise SpecFactoryError(
            f"Parent cycle detected while loading '{path}'"
        )
    visited = set(visited)
    visited.add(resolved_path)

    data = _load_source_file_raw(path)
    parent_name = data.get("parent")
    if parent_name is not None:
        if not isinstance(parent_name, str) or not parent_name.strip():
            raise SpecFactoryError(
                f"Invalid parent value in '{path}': {parent_name!r}"
            )
        parent_path = _resolve_source_path(parent_name, registry_dir)
        parent_data = _load_source_file_with_parent(
            parent_path, registry_dir, visited=visited, depth=depth + 1
        )
        child_data = dict(data)
        child_data.pop("parent", None)
        data = _deep_merge_dicts(parent_data, child_data)
    return {
        k: copy.deepcopy(v)
        for k, v in data.items()
        if k not in _KNOWN_SOURCE_METADATA_KEYS
    }


def _load_source_file(path, registry_dir):
    """Load source YAML, resolve parent chains, and strip metadata keys."""
    data = _load_source_file_with_parent(path, registry_dir)
    if len(data) == 1:
        key = next(iter(data))
        if key == "methods":
            methods_val = data[key]
            if isinstance(methods_val, list):
                return {"methods": copy.deepcopy(methods_val)}
            if isinstance(methods_val, dict):
                return dict(methods_val)
        if key in ("calibration", "settings") and isinstance(data[key], dict):
            return dict(data[key])
    return dict(data)


def _merge_chain(sources):
    """Sequential right-biased merge of a list of dicts."""
    result = {}
    for src in sources:
        if isinstance(src, dict):
            result.update(src)
    return result


def _is_method_override_dict(d):
    """Detect if a dict is a tuple-keyed method override.
    
    override_methods expects: {(stage, target, scheme): tag, ...}
    """
    if not d:
        return False
    return any(isinstance(k, tuple) for k in d)


def _apply_method_overrides(base_methods, overrides, stage_name):
    """Apply structured method overrides to a base methods dict.
    
    Wraps the base methods into the stage_sources format expected
    by override_methods, applies overrides, then unwraps.
    """
    from .method_overrides import override_methods

    # override_methods expects stage_sources: {stage_name: {"methods": <methods_dict>}}
    # Filter overrides to only those targeting this stage
    stage_overrides = {}
    for key, tag in overrides.items():
        if isinstance(key, tuple) and len(key) == 3:
            s_name, target, scheme = key
            if s_name == stage_name:
                stage_overrides[(s_name, target, scheme)] = tag
        elif isinstance(key, tuple) and len(key) == 2:
            target, scheme = key
            stage_overrides[(stage_name, target, scheme)] = tag

    if not stage_overrides:
        return base_methods

    stage_sources = {stage_name: {"methods": base_methods}}
    patched = override_methods(stage_sources, stage_overrides)
    return patched[stage_name]["methods"]


def _check_slot_tier(slot_dict, dim_name, slot_name):
    """Validate that a flat slot dict doesn't mix calibration and settings keys.

    Common settings keys (grid sizes, tolerances) should not appear in
    calibration slots and vice versa.
    """
    if not slot_dict:
        return
    if any(k in ("calibration", "settings", "methods") for k in slot_dict):
        return
    _KNOWN_SETTINGS_PREFIXES = ("n_", "tol", "max_iter", "grid_")
    _KNOWN_SETTINGS = {"n_a", "n_h", "n_w", "tol", "max_iter", "N_wage",
                        "n_sections", "store_cntn", "warmup_periods",
                        "normalisation", "fues_lb", "fues_eps_d"}

    has_settings = any(
        k in _KNOWN_SETTINGS or any(k.startswith(p) for p in _KNOWN_SETTINGS_PREFIXES)
        for k in slot_dict
    )
    has_params = any(
        k not in _KNOWN_SETTINGS and not any(k.startswith(p) for p in _KNOWN_SETTINGS_PREFIXES)
        for k in slot_dict
    )

    if has_settings and has_params:
        settings_keys = [k for k in slot_dict if k in _KNOWN_SETTINGS or
                         any(k.startswith(p) for p in _KNOWN_SETTINGS_PREFIXES)]
        param_keys = [k for k in slot_dict if k not in settings_keys]
        raise SpecFactoryError(
            f"Mixed tiers in slot '{slot_name}': "
            f"contains both parameter keys ({param_keys[:3]}) and "
            f"settings keys ({settings_keys[:3]}).\n"
            f"  x Cannot auto-wrap a slot dict that mixes calibration and settings.\n"
            f"  i Use the explicit form: {slot_name}={{\"calibration\": {{...}}, \"settings\": {{...}}}}"
        )


def _build_chain(source_names, slot_bindings, registry_dir, dim_name, source_cache):
    """Build the list of resolved items for one source chain.

    For calibration/settings: returns list of flat dicts.
    For methods: returns list of (dict | tuple-keyed-override).
    """
    chain = []
    for name in source_names:
        if name.startswith("$"):
            slot_name = name[1:]
            slot_val = slot_bindings.get(slot_name, {})
            if isinstance(slot_val, dict):
                tier_wrapped = any(
                    k in ("calibration", "settings", "methods") for k in slot_val
                )
                if tier_wrapped:
                    slot_val = slot_val.get(dim_name, {})
                if dim_name == "methods":
                    if _is_method_override_dict(slot_val):
                        chain.append(slot_val)
                        continue
                    if slot_val:
                        raise SpecFactoryError(
                            f"Slot '{slot_name}' for methods must use tuple keys "
                            f"{{(stage, target, scheme): tag}}. "
                            f"Received keys: {list(slot_val.keys())[:3]}"
                        )
                elif not tier_wrapped:
                    # Only run the tier-guess heuristic on unwrapped flat dicts.
                    # If the user already tier-wrapped, they've told us the tier
                    # explicitly and we trust their keys.
                    _check_slot_tier(slot_val, dim_name, slot_name)
            chain.append(slot_val if isinstance(slot_val, dict) else {})
        else:
            if name not in source_cache:
                path = _resolve_source_path(name, registry_dir)
                source_cache[name] = _load_source_file(path, registry_dir)
            chain.append(source_cache[name])
    return chain


def _merge_methods_dict(base_methods, overlay_methods):
    """Merge methods dicts by target+scheme instead of flat replacement."""
    base = copy.deepcopy(base_methods) if isinstance(base_methods, dict) else {}
    overlay = overlay_methods if isinstance(overlay_methods, dict) else {}

    for key, value in overlay.items():
        if key != "methods":
            base[key] = copy.deepcopy(value)

    base_entries = base.get("methods", [])
    overlay_entries = overlay.get("methods", [])
    if not isinstance(base_entries, list):
        base_entries = []
    if not isinstance(overlay_entries, list):
        overlay_entries = []

    by_target = {}
    for entry in base_entries:
        if isinstance(entry, dict) and "on" in entry:
            by_target[entry["on"]] = entry

    for overlay_entry in overlay_entries:
        if not isinstance(overlay_entry, dict):
            continue
        target = overlay_entry.get("on")
        if target is None or target not in by_target:
            base_entries.append(copy.deepcopy(overlay_entry))
            if target is not None:
                by_target[target] = base_entries[-1]
            continue

        base_entry = by_target[target]
        base_schemes = base_entry.get("schemes", [])
        overlay_schemes = overlay_entry.get("schemes", [])
        if not isinstance(base_schemes, list):
            base_schemes = []
            base_entry["schemes"] = base_schemes
        if not isinstance(overlay_schemes, list):
            overlay_schemes = []

        scheme_to_idx = {}
        for idx, scheme_obj in enumerate(base_schemes):
            if isinstance(scheme_obj, dict):
                scheme_name = scheme_obj.get("scheme")
                if scheme_name is not None:
                    scheme_to_idx[scheme_name] = idx

        for overlay_scheme in overlay_schemes:
            if not isinstance(overlay_scheme, dict):
                continue
            scheme_name = overlay_scheme.get("scheme")
            if scheme_name in scheme_to_idx:
                base_schemes[scheme_to_idx[scheme_name]] = copy.deepcopy(overlay_scheme)
            else:
                base_schemes.append(copy.deepcopy(overlay_scheme))
                if scheme_name is not None:
                    scheme_to_idx[scheme_name] = len(base_schemes) - 1

    base["methods"] = base_entries
    return base


def _resolve_methods_chain(chain, stage_name):
    """Resolve a methods chain using structured patching.
    
    File-backed sources are merged via right-biased update.
    Tuple-keyed override dicts (from $method_switch slots) are
    applied via override_methods at the (target, scheme) level.
    """
    base_methods = {}
    for item in chain:
        if not item:
            continue
        if _is_method_override_dict(item):
            base_methods = _apply_method_overrides(base_methods, item, stage_name)
        else:
            if isinstance(item, dict):
                base_methods = _merge_methods_dict(base_methods, item)
    return base_methods


def make(recipe, registry_dir, **slot_bindings):
    """Resolve all sources and return an immutable SpecGraph.

    Parameters
    ----------
    recipe : Recipe
        From load().
    registry_dir : str or Path
        Root of the registry directory. Source names are resolved
        as paths relative to this directory.
    **slot_bindings
        Named slot values. E.g., draw={"beta": 0.95},
        method_switch={("adjuster_cons", "cntn_to_dcsn_mover", "upper_envelope"): "NEGM"}.
        Unfilled slots contribute {} (empty dict).

    Returns
    -------
    SpecGraph
        Immutable. spec[stage_name][h]["calibration"] -> dict.
    """
    registry_dir = Path(registry_dir)
    source_cache = {}

    for slot_name in slot_bindings:
        if slot_name not in recipe.slots:
            warnings.warn(
                f"Slot '{slot_name}' provided but not declared in spec_factory. "
                f"Declared slots: {sorted(recipe.slots)}"
            )

    stage_data = {}

    for stage_name, stage_recipe in recipe.stages.items():
        stage_data[stage_name] = {
            "periods": stage_recipe.periods,
        }

        for dim in _DIMENSIONS:
            dim_recipe = getattr(stage_recipe, dim)
            all_sources = dim_recipe.get("all", [])

            if dim == "methods":
                all_chain = _build_chain(
                    all_sources, slot_bindings, registry_dir, dim, source_cache
                )
                resolved_methods = _resolve_methods_chain(all_chain, stage_name)

                if "methods" not in stage_data[stage_name]:
                    stage_data[stage_name]["methods"] = {}
                stage_data[stage_name]["methods"]["all"] = resolved_methods
            else:
                all_chain = _build_chain(
                    all_sources, slot_bindings, registry_dir, dim, source_cache
                )
                resolved_all = _merge_chain(all_chain)

                if dim not in stage_data[stage_name]:
                    stage_data[stage_name][dim] = {}
                stage_data[stage_name][dim]["all"] = resolved_all

            for key, range_sources in dim_recipe.items():
                if key == "all":
                    continue
                range_chain = _build_chain(
                    range_sources, slot_bindings, registry_dir, dim, source_cache
                )
                if dim == "methods":
                    base = copy.deepcopy(stage_data[stage_name]["methods"]["all"])
                    range_resolved = _resolve_methods_chain(
                        [base] + range_chain, stage_name
                    )
                    stage_data[stage_name]["methods"][key] = range_resolved
                else:
                    range_resolved = dict(stage_data[stage_name][dim]["all"])
                    range_resolved.update(_merge_chain(range_chain))
                    stage_data[stage_name][dim][key] = range_resolved

    return SpecGraph(stage_data)
