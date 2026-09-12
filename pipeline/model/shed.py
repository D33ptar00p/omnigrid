"""Run the allocation across every synchronous region and collect the result.

This is the orchestration layer: it partitions cells and plants by region (which
is what enforces the no-crossing constraint), builds each region's kernel, solves
it, and gathers per-plant sheds and per-cell mixes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse

from pipeline.model import cost, sinkhorn
from pipeline.model.demand import DemandSurface

METHOD = "shed.entropic_transport"


@dataclass
class RegionResult:
    region_id: str
    n_cells: int
    n_plants: int
    demand_gwh: float
    supply_gwh: float
    iterations: int
    converged: bool
    cell_error: float
    plant_error: float
    unplaced_gwh: float
    seconds: float

    @property
    def balance(self) -> float:
        """supply / demand. Far from 1 means the region is structurally
        infeasible -- usually an inventory gap, not a modelling failure."""
        return self.supply_gwh / self.demand_gwh if self.demand_gwh > 0 else float("inf")


@dataclass
class ShedModel:
    """Solved allocation for the whole world."""

    #: pi: cell x plant share of each cell's demand. Rows sum to 1.
    shares_by_cell: sparse.csr_matrix
    #: phi: cell x plant share of each plant's output. Columns sum to 1.
    shares_by_plant: sparse.csc_matrix
    #: GWh actually allocated, same sparsity.
    transport: sparse.csr_matrix
    regions: list[RegionResult] = field(default_factory=list)
    lambda_km: float = cost.DEFAULT_LAMBDA_KM
    notes: list[str] = field(default_factory=list)

    @property
    def total_unplaced_gwh(self) -> float:
        """Generation that could not be placed inside its own synchronous region.

        This is a real finding, not solver error. It concentrates in regions that
        genuinely export -- Northwest China and Quebec are the two largest -- over
        HVDC links the model does not represent. The unbalanced formulation lets
        those plants fall short rather than forcing their output onto local
        demand that does not exist, and the shortfall is reported instead of
        being absorbed silently.
        """
        return sum(r.unplaced_gwh for r in self.regions)

    @property
    def exporting_regions(self) -> list[RegionResult]:
        """Regions generating materially more than they consume."""
        return sorted((r for r in self.regions if r.balance > 1.15),
                      key=lambda r: -r.unplaced_gwh)

    @property
    def unconverged(self) -> list[RegionResult]:
        return [r for r in self.regions if not r.converged]

    def worst_balanced(self, n: int = 10) -> list[RegionResult]:
        return sorted(self.regions, key=lambda r: -abs(np.log(max(r.balance, 1e-9))))[:n]


def run(
    surface: DemandSurface,
    plant_lat: np.ndarray,
    plant_lon: np.ndarray,
    plant_supply_gwh: np.ndarray,
    plant_region: np.ndarray,
    *,
    lambda_km: float = cost.DEFAULT_LAMBDA_KM,
    rho: float = sinkhorn.DEFAULT_RHO,
    max_iter: int = sinkhorn.DEFAULT_MAX_ITER,
    k_nearest: int = cost.DEFAULT_K_NEAREST,
    near_km: float = cost.DEFAULT_NEAR_KM,
    progress: bool = False,
) -> ShedModel:
    n_cells, n_plants = len(surface), len(plant_lat)
    cell_slices = surface.region_slices()

    plant_order = np.argsort(plant_region, kind="stable")
    sorted_plant_regions = plant_region[plant_order]
    plant_slices: dict[str, np.ndarray] = {}
    if n_plants:
        bounds = np.flatnonzero(
            np.r_[True, sorted_plant_regions[1:] != sorted_plant_regions[:-1], True])
        plant_slices = {
            str(sorted_plant_regions[bounds[i]]): plant_order[bounds[i]:bounds[i + 1]]
            for i in range(len(bounds) - 1)
        }

    blocks: list[sparse.coo_matrix] = []
    results: list[RegionResult] = []
    notes: list[str] = []

    for region_id, cell_idx in cell_slices.items():
        plant_idx = plant_slices.get(region_id, np.empty(0, dtype=np.int64))
        demand = surface.demand_gwh[cell_idx]
        supply = plant_supply_gwh[plant_idx] if plant_idx.size else np.empty(0)

        if demand.sum() <= 0 or plant_idx.size == 0:
            # A region with demand but no plants is a real finding, not an error:
            # the inventory has no generation for somewhere people live.
            if demand.sum() > 0:
                notes.append(
                    f"{region_id}: {demand.sum() / 1000:,.0f} TWh of demand with no "
                    "plants in the inventory; left unserved rather than supplied "
                    "from across a grid boundary."
                )
            continue

        started = time.perf_counter()
        kernel = cost.build_kernel(
            surface.lat[cell_idx], surface.lon[cell_idx],
            plant_lat[plant_idx], plant_lon[plant_idx],
            lambda_km=lambda_km, k_nearest=k_nearest, near_km=near_km,
        )
        alloc = sinkhorn.solve(kernel.matrix, demand, supply, rho=rho, max_iter=max_iter)
        elapsed = time.perf_counter() - started

        coo = alloc.transport.tocoo()
        blocks.append(sparse.coo_matrix(
            (coo.data, (cell_idx[coo.row], plant_idx[coo.col])),
            shape=(n_cells, n_plants),
        ))

        results.append(RegionResult(
            region_id=region_id, n_cells=len(cell_idx), n_plants=len(plant_idx),
            demand_gwh=float(demand.sum()), supply_gwh=float(supply.sum()),
            iterations=alloc.iterations, converged=alloc.converged,
            cell_error=alloc.cell_error, plant_error=alloc.plant_error,
            unplaced_gwh=alloc.total_unplaced, seconds=elapsed,
        ))
        if progress:
            r = results[-1]
            print(f"  {region_id:26} {r.n_cells:6,} x {r.n_plants:6,}  "
                  f"{r.iterations:4} it  {elapsed:6.1f}s  "
                  f"bal {r.balance:5.2f}  {'' if r.converged else 'NOT CONVERGED'}",
                  flush=True)

    transport = (
        sparse.vstack([]) if not blocks
        else sum(blocks[1:], blocks[0]).tocsr() if len(blocks) > 1
        else blocks[0].tocsr()
    )
    if not blocks:
        transport = sparse.csr_matrix((n_cells, n_plants))

    model = ShedModel(
        shares_by_cell=_row_normalise(transport),
        shares_by_plant=_col_normalise(transport),
        transport=transport,
        regions=results,
        lambda_km=lambda_km,
        notes=notes,
    )
    return model


def _row_normalise(m: sparse.csr_matrix) -> sparse.csr_matrix:
    out = m.tocsr(copy=True)
    totals = np.asarray(out.sum(axis=1)).ravel()
    totals[totals <= 0] = 1.0
    out.data /= np.repeat(totals, np.diff(out.indptr))
    return out


def _col_normalise(m: sparse.csr_matrix) -> sparse.csc_matrix:
    out = m.tocsc(copy=True)
    totals = np.asarray(out.sum(axis=0)).ravel()
    totals[totals <= 0] = 1.0
    out.data /= np.repeat(totals, np.diff(out.indptr))
    return out
