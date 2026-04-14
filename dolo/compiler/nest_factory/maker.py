"""Nest assembly and backward solve-order derivation.

Supports two calling conventions:
- 0.1s (SpecGraph): make(nest_config, period_template, spec, sym_stages, upto=...)
- 0.1r (flat dicts): make(nest_config, period_template, calibration, settings, stage_sources, upto=...)

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
    # Avoid deep-copying node payloads (which may include immutable
    # MappingProxyType values in spec 0.1s); topology-only access is enough.
    reversed_G = graph.reverse(copy=False)
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


def make(nest_config, period_template, third=None, fourth=None,
         fifth=None, upto="specified"):
    """Build nest topology.

    Two calling conventions:

    **0.1s (SpecGraph)**::

        make(nest_config, period_template, spec, sym_stages, upto="specified")

    **0.1r (flat dicts)**::

        make(nest_config, period_template, calibration, settings, stage_sources, upto="specified")

    Detection: if ``third`` has a ``stage_names`` attribute, use the
    0.1s path. Otherwise, use the 0.1r path.

    Returns
    -------
    dict
        period_inst, graph, inter_conn, waves.
    """
    if third is not None and hasattr(third, 'stage_names'):
        return _make_from_spec(nest_config, period_template, third, fourth, upto=upto)
    else:
        return _make_from_flat(nest_config, period_template, third, fourth, fifth, upto=upto)


def _make_from_spec(nest_config, period_template, spec, sym_stages, upto="specified"):
    """0.1s path: build nest from SpecGraph."""
    from dolo.compiler.period_factory import make as make_period
    from dolo.compiler.period_factory.graphs import period_to_graph

    period_inst = make_period(spec, 0, period_template, sym_stages, upto=upto)

    graph = period_to_graph(period_inst)
    inter_conn = nest_config.get("inter_conn", {})
    waves = backward_paths(graph, inter_conn)

    return {
        "periods": [period_inst],
        "period_inst": period_inst,  # backward compat alias
        "graph": graph,
        "inter_conn": inter_conn,
        "waves": waves,
    }


def _make_from_flat(nest_config, period_template, calibration, settings,
                    stage_sources, upto="specified"):
    """0.1r path: build nest from flat dicts."""
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
        "periods": [period_inst],
        "period_inst": period_inst,  # backward compat alias
        "graph": graph,
        "inter_conn": inter_conn,
        "waves": waves,
    }
