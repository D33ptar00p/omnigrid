"""The allocation solver.

The invariants here are the model's promises: every cell's demand is fully met,
plant totals are respected as closely as the relaxation allows, and nothing is
allocated across a synchronous boundary.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from pipeline.model.sinkhorn import solve


def kernel(rows: int, cols: int, density: float = 0.4, seed: int = 0) -> sparse.csr_matrix:
    rng = np.random.default_rng(seed)
    m = sparse.random(rows, cols, density=density, random_state=seed,
                      data_rvs=lambda n: rng.random(n) + 0.01).tocsr()
    # Guarantee every row has at least one entry, or that cell is unservable.
    empty = np.flatnonzero(np.diff(m.indptr) == 0)
    if empty.size:
        extra = sparse.csr_matrix(
            (np.ones(empty.size), (empty, np.zeros(empty.size, dtype=int))),
            shape=m.shape)
        m = (m + extra).tocsr()
    return m


def balanced(rows=200, cols=30, seed=0):
    rng = np.random.default_rng(seed)
    K = kernel(rows, cols, seed=seed)
    d = rng.random(rows) * 100 + 1
    s = rng.random(cols) * 100 + 1
    return K, d, s / s.sum() * d.sum()


def test_every_cell_demand_is_fully_met():
    """Constraint (3) is the hard one: a cell's shares must sum to exactly 1."""
    K, d, s = balanced()
    a = solve(K, d, s)
    rows = np.asarray(a.shares_by_cell().sum(axis=1)).ravel()
    assert np.allclose(rows, 1.0, atol=1e-12)
    assert a.cell_error < 1e-12


def test_plant_output_is_respected_within_the_relaxation():
    K, d, s = balanced()
    a = solve(K, d, s)
    placed = np.asarray(a.transport.sum(axis=0)).ravel()
    assert a.total_unplaced < 0.01 * s.sum()
    assert np.allclose(placed, s, rtol=0.05)


def test_shares_by_plant_columns_sum_to_one():
    """phi is the supply shed: where a plant's output goes."""
    K, d, s = balanced()
    cols = np.asarray(solve(K, d, s).shares_by_plant().sum(axis=0)).ravel()
    assert np.allclose(cols[cols > 0], 1.0, atol=1e-12)


def test_energy_is_conserved_overall():
    K, d, s = balanced()
    a = solve(K, d, s)
    assert a.transport.sum() == pytest.approx(d.sum(), rel=1e-9)


def test_closer_plants_receive_more_of_a_cells_demand():
    """The distance decay must actually bite, or the model says nothing."""
    K = sparse.csr_matrix(np.array([[1.0, 0.1]]))  # plant 0 much closer
    a = solve(K, np.array([100.0]), np.array([50.0, 50.0]))
    pi = a.shares_by_cell().toarray()[0]
    assert pi[0] > pi[1]


def test_allocation_is_many_to_many_not_a_hard_partition():
    """A weighted Voronoi or an LP optimum would give each cell one plant. The
    entropic solution must spread, because reality does."""
    K, d, s = balanced()
    per_cell = np.diff(solve(K, d, s).shares_by_cell().indptr)
    assert per_cell.mean() > 2


def test_unservable_plant_falls_short_instead_of_diverging():
    """A plant with no demand in reach -- mine-mouth, island hydro -- must be
    reported as unplaced rather than stalling the iteration."""
    K = sparse.csr_matrix(np.array([[1.0, 0.0]]))
    a = solve(K, np.array([100.0]), np.array([100.0, 500.0]))
    assert np.isfinite(a.transport.data).all()
    assert a.unplaced_gwh[1] == pytest.approx(500.0)
    assert np.asarray(a.shares_by_cell().sum(axis=1)).ravel()[0] == pytest.approx(1.0)


def test_surplus_region_places_what_it_can_and_reports_the_rest():
    """Northwest China generates 2.3x its local demand. The surplus must be
    reported, not forced onto demand that does not exist."""
    K, d, _ = balanced()
    s = np.full(30, d.sum() / 30 * 2.0)  # twice the demand
    a = solve(K, d, s)
    assert a.transport.sum() == pytest.approx(d.sum(), rel=1e-9)
    assert a.total_unplaced == pytest.approx(s.sum() - d.sum(), rel=0.02)


def test_empty_region_is_handled():
    a = solve(sparse.csr_matrix((0, 0)), np.array([]), np.array([]))
    assert a.converged and a.transport.nnz == 0


def test_zero_demand_does_not_divide_by_zero():
    K, _, s = balanced()
    a = solve(K, np.zeros(200), s)
    assert np.isfinite(a.transport.data).all() if a.transport.nnz else True
    assert a.total_unplaced == pytest.approx(s.sum())


def test_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="does not match"):
        solve(kernel(10, 5), np.ones(9), np.ones(5))


def test_rejects_negative_inputs():
    with pytest.raises(ValueError, match="non-negative"):
        solve(kernel(10, 5), -np.ones(10), np.ones(5))


def test_solution_is_deterministic():
    K, d, s = balanced()
    assert np.allclose(solve(K, d, s).transport.toarray(),
                       solve(K, d, s).transport.toarray())


def test_population_served_sums_to_the_population():
    """The conservation identity behind the headline number: pi sums to 1 across
    plants for every served cell, so pi-weighted population summed over all
    plants must recover the population itself. If this drifts, either demand is
    going unserved or the allocation is leaking."""
    K, d, s = balanced(rows=150, cols=20)
    a = solve(K, d, s)
    pi = a.shares_by_cell()
    rng = np.random.default_rng(7)
    population = rng.random(150) * 10_000

    served = np.asarray(pi.T.multiply(population).sum(axis=1)).ravel()
    assert served.sum() == pytest.approx(population.sum(), rel=1e-9)
