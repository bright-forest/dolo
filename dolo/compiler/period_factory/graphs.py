"""Period graph construction and solve-order topology derivation.

Migrated from kikku/dynx/graphs.py (spec 0.1r).
"""

from __future__ import annotations
from typing import Any
import networkx as nx


def _extract_interface(mod):
    """Extract prestate / poststate interface from a SymbolicModel."""
    symbols = mod.symbols
    prestate = list(symbols.get("prestate", []))
    kind = getattr(mod, "kind", "standard") or "standard"
    branch_poststates = None
    if kind == "branching" and hasattr(mod, "branch_poststates"):
        raw = mod.branch_poststates
        branch_poststates = {
            branch: list(fields.keys()) if isinstance(fields, dict) else list(fields)
            for branch, fields in raw.items()
        }
        seen = {}
        for branch, fields in branch_poststates.items():
            for f in fields:
                if f in seen:
                    raise ValueError(
                        f"Poststate field '{f}' appears in branches "
                        f"'{seen[f]}' and '{branch}' of stage "
                        f"'{getattr(mod, 'name', '?')}'. "
                        f"Field names must be disjoint across branches "
                        f"(spec 0.1l flat-disjointness rule)."
                    )
                seen[f] = branch
        poststate = list(dict.fromkeys(
            f for fields in branch_poststates.values() for f in fields
        ))
    else:
        poststate = list(symbols.get("poststates", []))
    return {
        "prestate": prestate,
        "poststate": poststate,
        "branch_poststates": branch_poststates,
        "kind": kind,
    }


def period_to_graph(period_dict):
    """Build a directed graph from a canonical period dict."""
    stages = period_dict["stages"]
    connectors = period_dict.get("connectors", [])
    G = nx.DiGraph()
    interfaces = {}
    for name, mod in stages.items():
        iface = _extract_interface(mod)
        interfaces[name] = iface
        G.add_node(name, prestate=iface["prestate"], poststate=iface["poststate"],
                   kind=iface["kind"], branch_poststates=iface["branch_poststates"], mod=mod)
    covered_fields = set()
    for conn in connectors:
        for src_field, tgt_field in conn.items():
            src_stage = _find_stage_with_poststate(interfaces, src_field)
            tgt_stage = _find_stage_with_prestate(interfaces, tgt_field)
            if src_stage and tgt_stage:
                attrs = {"rename": {src_field: tgt_field}}
                bp = interfaces[src_stage]["branch_poststates"]
                if bp:
                    for branch, fields in bp.items():
                        if src_field in fields:
                            attrs["branch"] = branch
                            break
                G.add_edge(src_stage, tgt_stage, **attrs)
                covered_fields.add(src_field)
    for name_a, iface_a in interfaces.items():
        bp = iface_a["branch_poststates"]
        if bp:
            for branch, fields in bp.items():
                for field in fields:
                    if field in covered_fields:
                        continue
                    tgt = _find_stage_with_prestate(interfaces, field, exclude=name_a)
                    if tgt:
                        G.add_edge(name_a, tgt, rename={}, branch=branch)
                        covered_fields.add(field)
        else:
            for field in iface_a["poststate"]:
                if field in covered_fields:
                    continue
                tgt = _find_stage_with_prestate(interfaces, field, exclude=name_a)
                if tgt:
                    G.add_edge(name_a, tgt, rename={})
                    covered_fields.add(field)
    if not nx.is_directed_acyclic_graph(G):
        cycle = nx.find_cycle(G)
        raise ValueError(f"Period graph has a cycle: {cycle}")
    return G


def forward_order(graph):
    """Return stages in forward (topological) order."""
    return list(nx.topological_sort(graph))


def _find_stage_with_poststate(interfaces, field, *, exclude=None):
    for name, iface in interfaces.items():
        if name == exclude:
            continue
        if field in iface["poststate"]:
            return name
    return None


def _find_stage_with_prestate(interfaces, field, *, exclude=None):
    for name, iface in interfaces.items():
        if name == exclude:
            continue
        if field in iface["prestate"]:
            return name
    return None
