import yaml
from dolo.numeric.decision_rule import DecisionRule
import numpy as np
from interpolation.splines import eval_linear
from dolo.compiler.model import Model
from .results import EGMResult


def egm(
    model: Model,
    dr0: DecisionRule = None,
    verbose: bool = False,
    details: bool = True,
    a_grid=None,
    η_tol=1e-6,
    maxit=1000,
    grid=None,
    dp=None,
    return_internals: bool = False,
):
    """
    Endogenous Grid Method solver.

    Args:
        model: compiled Dolo Model (dtcc type with EGM blocks)
        dr0: initial decision rule (callable(i, s) -> controls, or None)
        verbose: print iteration progress
        details: (unused, kept for API compat)
        a_grid: (numpy-array) vector of points used to discretize poststates; must be increasing
        η_tol: convergence tolerance on endogenous grid
        maxit: maximum number of iterations
        grid: pre-discretized grid (optional; avoids re-discretizing)
        dp: pre-discretized process (optional; avoids re-discretizing)
        return_internals: if True, return (EGMResult, internals_dict) where
            internals_dict contains 'sa0', 'xa0', 'z' — the raw endogenous-grid
            arrays from the last iteration.  These can be passed to a subsequent
            egm() call via dr0_internals to avoid cubic-resampling error.

    Returns:
        EGMResult (or (EGMResult, dict) if return_internals=True)
    """

    assert len(model.symbols["states"]) == 1
    assert (
        len(model.symbols["controls"]) == 1
    )  # we probably don't need this restriction

    from dolo.numeric.processes import IIDProcess

    iid_process = isinstance(model.exogenous, IIDProcess)

    def vprint(t):
        if verbose:
            print(t)

    p = model.calibration["parameters"]

    if grid is None and dp is None:
        grid, dp = model.discretize()

    s = grid["endo"].nodes

    funs = model.__original_gufunctions__
    h = funs["expectation"]
    gt = funs["half_transition"]
    τ = funs["direct_response_egm"]
    aτ = funs["reverse_state"]
    lb = funs["arbitrage_lb"]
    ub = funs["arbitrage_ub"]

    if dr0 is None:
        x0 = model.calibration["controls"]
        dr0 = lambda i, s: x0[None, :].repeat(s.shape[0], axis=0)

    n_m = dp.n_nodes
    n_x = len(model.symbols["controls"])

    if a_grid is None:
        raise Exception("You must supply a grid for the post-states.")

    assert a_grid.ndim == 1
    a = a_grid[:, None]
    N_a = a.shape[0]

    N = s.shape[0]

    n_h = len(model.symbols["expectations"])

    xa = np.zeros((n_m, N_a, n_x))
    sa = np.zeros((n_m, N_a, 1))
    xa0 = np.zeros((n_m, N_a, n_x))
    sa0 = np.zeros((n_m, N_a, 1))

    z = np.zeros((n_m, N_a, n_h))

    if verbose:
        headline = "|{0:^4} | {1:10} |".format("N", " Error")
        stars = "-" * len(headline)
        print(stars)
        print(headline)
        print(stars)

    for it in range(0, maxit):

        if it == 0:
            drfut = dr0

        else:

            def drfut(i, ss):
                if iid_process:
                    i = 0
                m = dp.node(i)
                l_ = lb(m, ss, p)
                u_ = ub(m, ss, p)
                x = eval_linear((sa0[i, :, 0],), xa0[i, :, 0], ss)[:, None]
                x = np.minimum(x, u_)
                x = np.maximum(x, l_)
                return x

        z[:, :, :] = 0

        for i_m in range(n_m):
            m = dp.node(i_m)
            for i_M in range(dp.n_inodes(i_m)):
                w = dp.iweight(i_m, i_M)
                M = dp.inode(i_m, i_M)
                S = gt(m, a, M, p)
                X = drfut(i_M, S)
                z[i_m, :, :] += w * h(M, S, X, p)
            xa[i_m, :, :] = τ(m, a, z[i_m, :, :], p)
            sa[i_m, :, :] = aτ(m, a, xa[i_m, :, :], p)

        if it > 1:
            η = abs(xa - xa0).max() + abs(sa - sa0).max()
        else:
            η = 1

        vprint("|{0:4} | {1:10.3e} |".format(it, η))

        if η < η_tol:
            break

        sa0[...] = sa
        xa0[...] = xa

    # resample the result on the standard grid
    endo_grid = grid["endo"]
    exo_grid = grid["exo"]
    mdr = DecisionRule(exo_grid, endo_grid, dprocess=dp, interp_method="cubic")

    mdr.set_values(
        np.concatenate([drfut(i, s)[None, :, :] for i in range(n_m)], axis=0)
    )

    sol = EGMResult(mdr, it, dp, (η < η_tol), η_tol, η)

    if return_internals:
        internals = {
            "sa0": sa0.copy(),
            "xa0": xa0.copy(),
            "z": z.copy(),
        }
        return sol, internals

    return sol


def make_egm_dr0_from_internals(internals, dp, funs, p, iid_process):
    """
    Build a dr0 callable from raw EGM internals (sa0, xa0).

    This produces the same linear-interpolation decision rule that egm()
    uses between its internal iterations — avoiding the cubic-resampling
    error that comes from passing sol.dr between separate egm() calls.

    Args:
        internals: dict with 'sa0' and 'xa0' from egm(return_internals=True)
        dp: discretized process
        funs: model.__original_gufunctions__
        p: parameter vector
        iid_process: bool

    Returns:
        callable(i, ss) -> controls
    """
    sa0 = internals["sa0"]
    xa0 = internals["xa0"]
    lb = funs["arbitrage_lb"]
    ub = funs["arbitrage_ub"]

    def drfut(i, ss):
        if iid_process:
            i = 0
        m = dp.node(i)
        l_ = lb(m, ss, p)
        u_ = ub(m, ss, p)
        x = eval_linear((sa0[i, :, 0],), xa0[i, :, 0], ss)[:, None]
        x = np.minimum(x, u_)
        x = np.maximum(x, l_)
        return x

    return drfut
