"""Save and load DDSL nests (.nst files).

A nest is the central model object. It contains:
  - periods: list of {stages: {name: SymbolicModel}, connectors: [...]}
    These are the dolo+ configured stage objects — the single source of truth.
  - solutions (optional): list of {stage: {perch: {qty: ndarray}}} per period
  - inter_conn: dict (state renaming across periods)

The .nst format is a single pickle file containing the configured periods
and (optionally) the solution arrays. Graph topology is NOT saved — it is
reconstructed from the period template on load.

Usage:
    save_nest(nest, 'mymodel.nst')                    # with solutions
    save_nest(nest, 'mymodel.nst', solutions=False)   # periods only (unsolved)

    nest = load_nest('mymodel.nst')
    # nest['periods'] always present (dolo+ SymbolicModel objects)
    # nest['solutions'] present if saved, else empty list
    # nest['graph'] and nest['inter_conn'] reconstructed if period template available
"""

import pickle
from pathlib import Path
from typing import Any


def save_nest(
    nest: dict,
    path: str | Path,
    solutions: bool = True,
    metadata: dict | None = None,
) -> Path:
    """Save a nest to a .nst file.

    Parameters
    ----------
    nest : dict
        Must contain 'periods' (list of period dicts with dolo+ stage objects).
        May contain 'solutions', 'graph', 'inter_conn'.
    path : str or Path
        Output file path. Convention: .nst suffix.
    solutions : bool
        If True (default), include solution arrays. If False, save only
        the configured periods (unsolved nest).
    metadata : dict, optional
        Extra metadata to store (theta, method, settings, timestamp, etc.).

    Returns
    -------
    Path to the saved file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    bundle = {
        'periods': nest['periods'],
        'inter_conn': nest.get('inter_conn', {}),
        'metadata': metadata or {},
    }

    if solutions and 'solutions' in nest:
        bundle['solutions'] = nest['solutions']

    with path.open('wb') as f:
        pickle.dump(bundle, f, protocol=pickle.HIGHEST_PROTOCOL)

    return path


def load_nest(path: str | Path) -> dict:
    """Load a nest from a .nst file.

    Returns
    -------
    dict with keys:
        'periods': list of period dicts (dolo+ SymbolicModel objects intact)
        'solutions': list of solution dicts (if saved, else empty list)
        'inter_conn': dict (state renaming)
        'metadata': dict (theta, method, etc.)
        'graph': None (reconstruct via period_to_graph if needed)
    """
    path = Path(path)

    with path.open('rb') as f:
        bundle = pickle.load(f)

    return {
        'periods': bundle['periods'],
        'solutions': bundle.get('solutions', []),
        'inter_conn': bundle.get('inter_conn', {}),
        'metadata': bundle.get('metadata', {}),
        'graph': None,  # reconstruct if needed
    }


def nest_info(path: str | Path) -> dict:
    """Quick summary of a .nst file without loading full arrays.

    Returns
    -------
    dict with: n_periods, stage_names, has_solutions, metadata, file_size_mb
    """
    path = Path(path)
    size_mb = path.stat().st_size / (1024 * 1024)

    nest = load_nest(path)
    periods = nest['periods']

    stage_names = []
    if periods:
        stage_names = list(periods[0].get('stages', {}).keys())

    return {
        'n_periods': len(periods),
        'stage_names': stage_names,
        'has_solutions': len(nest['solutions']) > 0,
        'metadata': nest['metadata'],
        'file_size_mb': round(size_mb, 2),
    }
