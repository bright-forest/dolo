"""Spec factory resolution engine (spec 0.1s).

Resolves a Recipe into an immutable SpecGraph by loading source
files from the registry, substituting slot bindings, and running
the sequential merge per (stage, dimension, period-group).
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from .graph import SpecGraph
from .loader import SpecFactoryError


_DIMENSIONS = ("calibration", "settings", "methods")
_KNOWN_SOURCE_METADATA_KEYS = {"parent", "description", "version", "__comment__"}

# Items in a list of dicts are matched by these key fields, in priority
# order. If items in both base and overlay share one of these keys,
# do structural match-and-merge; otherwise the overlay list replaces
# the base list wholesale.
_LIST_KEY_FIELDS = ("on", "scheme")

_TIER_NAMES = frozenset({"calibration", "settings", "methods"})


def _deep_merge(base, overlay):
    """Recursive partial merge over dicts, keyed lists, and scalars."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        result = dict(base)
        for k, v in overlay.items():
            if k in result:
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = copy.deepcopy(v)
        return result
    if isinstance(base, list) and isinstance(overlay, list):
        return _merge_keyed_list(base, overlay)
    return copy.deepcopy(overlay)


def _merge_keyed_list(base, overlay):
    """Match list-of-dicts items by their structural key field."""
    if not (all(isinstance(x, dict) for x in base)
            and all(isinstance(x, dict) for x in overlay)):
        return copy.deepcopy(overlay)
    key_field = None
    for kf in _LIST_KEY_FIELDS:
        if all(kf in x for x in base + overlay):
            key_field = kf
            break
    if key_field is None:
        return copy.deepcopy(overlay)
    result = []
    seen = set()
    for x in base:
        ov = next((o for o in overlay if o.get(key_field) == x[key_field]), None)
        if ov is not None:
            result.append(_deep_merge(x, ov))
            seen.add(x[key_field])
        else:
            result.append(copy.deepcopy(x))
    for o in overlay:
        if o.get(key_field) not in seen:
            result.append(copy.deepcopy(o))
    return result


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
    """Sequential recursive merge of a chain of dicts."""
    result = {}
    for src in sources:
        if isinstance(src, dict):
            result = _deep_merge(result, src)
    return result


def _build_chain(source_names, slot_bindings, registry_dir, dim_name, source_cache):
    chain = []
    for name in source_names:
        if name.startswith("$"):
            slot_name = name[1:]
            slot_val = slot_bindings.get(slot_name, {})
            if not isinstance(slot_val, dict):
                chain.append({})
                continue
            if slot_val and set(slot_val).issubset(_TIER_NAMES):
                inner = slot_val.get(dim_name, {})
                # Tier bundles: route inner dict/list per dimension. Methods-slot
                # YAML is {"methods": [ ... ]}; the inner value for key
                # "methods" is a list and must stay wrapped so _merge_chain
                # merges a dict (bare lists are skipped).
                if dim_name == "methods":
                    if isinstance(inner, list):
                        chain.append({"methods": inner})
                    elif isinstance(inner, dict):
                        chain.append(inner)
                    else:
                        chain.append({})
                else:
                    chain.append(inner if isinstance(inner, dict) else {})
            else:
                chain.append(slot_val)
        else:
            if name not in source_cache:
                path = _resolve_source_path(name, registry_dir)
                source_cache[name] = _load_source_file(path, registry_dir)
            chain.append(source_cache[name])
    return chain


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
        method_switch={"methods": [{"on": "builder", "schemes": [...]}]}.
        Unfilled slots contribute {} (empty dict).

    Returns
    -------
    SpecGraph
        Immutable. spec[stage_name][h]["calibration"] -> dict.
    """
    registry_dir = Path(registry_dir)
    source_cache = {}

    unknown = [s for s in slot_bindings if s not in recipe.slots]
    if unknown:
        raise SpecFactoryError(
            f"Slot bindings reference undeclared slots: {sorted(unknown)}\n"
            f"  Declared slots: {sorted(recipe.slots)}\n"
            f"  Hint: check spec_factory.yaml or fix the slot name."
        )

    stage_data = {}

    for stage_name, stage_recipe in recipe.stages.items():
        stage_data[stage_name] = {
            "periods": stage_recipe.periods,
        }

        for dim in _DIMENSIONS:
            dim_recipe = getattr(stage_recipe, dim)
            all_sources = dim_recipe.get("all", [])
            chain = _build_chain(all_sources, slot_bindings, registry_dir, dim, source_cache)
            resolved = _merge_chain(chain)
            stage_data[stage_name][dim] = {"all": resolved}
            for key, range_sources in dim_recipe.items():
                if key == "all":
                    continue
                rng_chain = _build_chain(range_sources, slot_bindings, registry_dir, dim, source_cache)
                stage_data[stage_name][dim][key] = _merge_chain([resolved] + rng_chain)

    return SpecGraph(stage_data)
