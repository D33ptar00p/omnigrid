"""Unbalanced Sinkhorn: the allocation itself.

Two constraints define the problem:

    (2) each plant's allocated output sums to its estimated annual generation
    (3) each cell's demand is fully met

Those are row-sum and column-sum constraints on a transport matrix. Add a
distance-decay preference and the result is entropy-regularised optimal
transport, which is identically the doubly-constrained gravity model, and is
solved by Sinkhorn iteration in O(nnz) per pass:

    u <- d / (K  @ v)
    v <- s / (K' @ u)

The plant-side update is *relaxed* rather than exact. Balanced Sinkhorn requires
supply and demand to match exactly within every region and stalls or diverges
wherever a plant has no demand inside its cutoff -- mine-mouth plants, island
hydro, captive industrial generation. Relaxing constraint (2) from hard to strong
is both numerically necessary and more honest, since plants genuinely do export
across region boundaries. The plants whose output could not be placed are
reported rather than quietly absorbed.

Why not the obvious alternatives: a weighted Voronoi gives each cell exactly one
plant, which cannot satisfy (2) and is physically false; a hard LP optimum sits
at a vertex of the transport polytope, so again almost every cell gets a single
plant, and it is discontinuous -- a 1 km cost change flips whole regions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse

#: KL relaxation on the plant marginal. Higher is closer to a hard constraint;
#: 200 keeps plant totals within ~1% where the problem is feasible, while still
#: letting an unservable plant fall short instead of driving the iteration to
#: infinity. Higher values tighten the plant constraint but converge more slowly.
DEFAULT_RHO = 200.0

#: Generous, because each pass is two sparse mat-vecs and regions are small:
#: the whole world converges in ~18s. A cap that bites silently would leave
#: marginals wrong in exactly the largest, most-looked-at regions.
DEFAULT_MAX_ITER = 20_000
DEFAULT_TOLERANCE = 1e-7

#: Guards against dividing by a marginal that has underflowed to zero.
_FLOOR = 1e-300


@dataclass(slots=True)
class Allocation:
    """The solved transport plan for one region, plus how well it converged."""

    #: T, shape (n_cells, n_plants), in GWh.
    transport: sparse.csr_matrix
    iterations: int
    converged: bool
    #: max |row_sum - demand| / demand
    cell_error: float
    #: max |col_sum - supply| / supply
    plant_error: float
    #: Per-plant GWh that could not be placed within the region.
    unplaced_gwh: np.ndarray

    @property
    def total_unplaced(self) -> float:
        return float(self.unplaced_gwh.sum())

    def shares_by_cell(self) -> sparse.csr_matrix:
        """pi_ij: what fraction of cell i's demand comes from plant j.

        Rows sum to 1. This is what drives colour on the map.
        """
        return _row_normalise(self.transport)

    def shares_by_plant(self) -> sparse.csc_matrix:
        """phi_ij: what fraction of plant j's output goes to cell i.

        Columns sum to 1. This is the actual "spread" -- the supply shed.
        """
        csc = self.transport.tocsc(copy=True)
        totals = np.asarray(csc.sum(axis=0)).ravel()
        totals[totals <= 0] = 1.0
        csc.data /= np.repeat(totals, np.diff(csc.indptr))
        return csc


def _row_normalise(matrix: sparse.csr_matrix) -> sparse.csr_matrix:
    out = matrix.tocsr(copy=True)
    totals = np.asarray(out.sum(axis=1)).ravel()
    totals[totals <= 0] = 1.0
    out.data /= np.repeat(totals, np.diff(out.indptr))
    return out


def solve(
    kernel: sparse.csr_matrix,
    demand: np.ndarray,
    supply: np.ndarray,
    *,
    rho: float = DEFAULT_RHO,
    max_iter: int = DEFAULT_MAX_ITER,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Allocation:
    """Solve one region.

    `demand` is per-cell GWh, `supply` per-plant GWh. Both must be non-negative.
    """
    n_cells, n_plants = kernel.shape
    demand = np.ascontiguousarray(demand, dtype=np.float64)
    supply = np.ascontiguousarray(supply, dtype=np.float64)
    if demand.shape != (n_cells,) or supply.shape != (n_plants,):
        raise ValueError(
            f"kernel {kernel.shape} does not match demand {demand.shape} "
            f"and supply {supply.shape}"
        )
    if (demand < 0).any() or (supply < 0).any():
        raise ValueError("demand and supply must be non-negative")

    if n_cells == 0 or n_plants == 0 or kernel.nnz == 0:
        empty = sparse.csr_matrix((n_cells, n_plants))
        return Allocation(empty, 0, True, 0.0, 0.0, supply.copy())

    kt = kernel.T.tocsr()  # precomputed once: the transpose is half the work
    u = np.ones(n_cells, dtype=np.float64)
    v = np.ones(n_plants, dtype=np.float64)
    # Relaxation exponent: 1 would be the exact (balanced) update.
    exponent = rho / (rho + 1.0)

    iterations = 0
    converged = False
    for iterations in range(1, max_iter + 1):
        u = demand / np.maximum(kernel @ v, _FLOOR)
        v_next = (supply / np.maximum(kt @ u, _FLOOR)) ** exponent

        # Convergence is tested on the scaling vectors, not on the plant
        # marginal. The relaxed update converges to a fixed point where the
        # plant marginal is deliberately *not* exact -- testing that instead
        # would mean never declaring convergence on a relaxed solve.
        if iterations % 10 == 0 or iterations == max_iter:
            delta = _relative_error(v_next, v)
            v = v_next
            if delta < tolerance:
                converged = True
                break
        else:
            v = v_next

    # One final row update. The loop ends on a plant-side update, which leaves
    # the cell marginal slightly off; constraint (3) is the hard one -- every
    # cell's shares must sum to 1 -- so it gets the last word.
    u = demand / np.maximum(kernel @ v, _FLOOR)

    transport = _scale(kernel, u, v)
    cell_error, plant_error = _marginal_errors(kernel, u, v, demand, supply)
    placed = np.asarray(transport.sum(axis=0)).ravel()
    unplaced = np.maximum(supply - placed, 0.0)

    return Allocation(transport, iterations, converged, cell_error, plant_error, unplaced)


def _scale(kernel: sparse.csr_matrix, u: np.ndarray, v: np.ndarray) -> sparse.csr_matrix:
    """T = diag(u) K diag(v), without densifying anything."""
    out = kernel.tocsr(copy=True)
    out.data *= np.repeat(u, np.diff(out.indptr))
    out.data *= v[out.indices]
    return out


def _marginal_errors(kernel, u, v, demand, supply) -> tuple[float, float]:
    row = u * (kernel @ v)
    col = v * (kernel.T @ u)
    return (_relative_error(row, demand), _relative_error(col, supply))


def _relative_error(got: np.ndarray, want: np.ndarray) -> float:
    mask = want > 0
    if not mask.any():
        return 0.0
    return float(np.max(np.abs(got[mask] - want[mask]) / want[mask]))
