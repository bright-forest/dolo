"""Nest assembly and backward solve-order derivation.

backward_paths migrated from kikku/dynx/graphs.py (spec 0.1r).
"""

from __future__ import annotations
import networkx as nx


def backward_paths(graph, inter_connector):
    """Return independently solvable stage chains for backward iteration."""
    entry_fields = set(inter_connector.keys())
    initial = set()
    for node, data in graph.nodes(data=True):
        post = set(data.get("poststate", []))
        if post & entry_fields:
            initial.add(node)
    reversed_G = graph.reverse(copy=True)
    resolved = set()
    waves = []
    all_nodes = set(graph.nodes)
    while resolved != all_nodes:
        wave = []
        for node in all_nodes - resolved:
            preds_in_reversed = set(reversed_G.predecessors(node))
            unresolved_deps = preds_in_reversed - resolved
            if not unresolved_deps:
                if node in initial or _all_successors_resolved(reversed_G, node, resolved):
                    wave.append(node)
        if not wave:
            remaining = all_nodes - resolved
            wave = sorted(remaining)
        wave.sort()
        waves.append(wave)
        resolved.update(wave)
    return waves


def _all_successors_resolved(reversed_G, node, resolved):
    return all(s in resolved for s in reversed_G.successors(node))


def make(nest_config, period_template, calibration, settings,
         stage_sources, upto="specified"):
    """Build nest topology from one repeated period template (spec 0.1r).

    In 0.1r, all periods use the same template and the same
    calibration/settings/methods. Per-period variation (epochs,
    spec_factory recipes) is deferred to spec 0.1s.

    Parameters
    ----------
    nest_config : dict
        From ``nest_factory.load()``. Must contain ``inter_conn``.
    period_template : dict
        From ``period_factory.load()``. Stage list + wiring.
    calibration : dict
        Economic parameters.
    settings : dict
        Numerical settings.
    stage_sources : dict
        Pre-loaded stage data per stage name.
    upto : str, optional
        Passed through to ``period_factory.make``.

    Returns
    -------
    dict
        ``period_inst``, ``graph``, ``waves``, ``inter_conn`` — one canonical
        period instance (reused across horizon indices in 0.1r).
    """
    from dolo.compiler.period_factory import make as make_period
    from dolo.compiler.period_factory.graphs import period_to_graph

    period_inst = make_period(
        calibration, settings, stage_sources, period_template,
        upto=upto,
    )

    graph = period_to_graph(period_inst)
    inter_conn = nest_config.get("inter_conn", {})
    waves = backward_paths(graph, inter_conn)

    return {
        "period_inst": period_inst,
        "graph": graph,
        "inter_conn": inter_conn,
        "waves": waves,
    }
