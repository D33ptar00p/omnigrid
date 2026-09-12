"""Build the sparse transport kernel: which plants can plausibly serve which cells.

The kernel is  K_ij = exp(-c_ij / lambda)  masked to cells and plants in the same
synchronous region and within a cutoff radius. Everything about the shape of the
resulting sheds comes from `c_ij` and `lambda`:

  * lambda is the distance-decay scale in km. It is the one interpretable knob in
    the model, and it is *fitted* against eGRID and ENTSO-E rather than chosen.
  * the cutoff is 5*lambda, beyond which exp(-5) < 0.7% of the peak contributes
    nothing visible but costs real memory.

Distances are computed on ECEF coordinates rather than lat/lon: there is no
longitude wraparound to special-case, and the chord distance converts exactly to
great-circle, so the KD-tree search is both correct and fast.

Tier 1 (here) is great-circle. Tier 2 -- an H3 graph geodesic weighted by whether
a gridfinder line crosses each cell -- is what makes sheds follow grid corridors
instead of blooming as circles, and slots in by replacing `distances()`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree

EARTH_RADIUS_KM = 6371.0088

#: Distance-decay scale, km. Fitted against held-out ground truth; this is the
#: central value, with half and double shipped as a sensitivity control.
DEFAULT_LAMBDA_KM = 150.0

#: Per cell, keep the union of the K nearest plants and everything inside
#: NEAR_KM. The union matters: K-nearest alone starves a cell in a dense
#: cluster, and a radius alone starves one in an empty region.
DEFAULT_K_NEAREST = 48
DEFAULT_NEAR_KM = 150.0


def to_ecef(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Lat/lon degrees -> unit-sphere Cartesian, scaled to km."""
    la, lo = np.radians(lat), np.radians(lon)
    cos_la = np.cos(la)
    return np.column_stack((
        EARTH_RADIUS_KM * cos_la * np.cos(lo),
        EARTH_RADIUS_KM * cos_la * np.sin(lo),
        EARTH_RADIUS_KM * np.sin(la),
    ))


def chord_to_great_circle(chord_km: np.ndarray) -> np.ndarray:
    """Straight-line distance through the sphere -> distance along the surface.

    Exact, not an approximation: 2R*asin(chord / 2R).
    """
    ratio = np.clip(chord_km / (2 * EARTH_RADIUS_KM), 0.0, 1.0)
    return 2 * EARTH_RADIUS_KM * np.arcsin(ratio)


@dataclass(frozen=True, slots=True)
class Kernel:
    """Sparse cell x plant transport kernel for one synchronous region."""

    matrix: sparse.csr_matrix          # K, shape (n_cells, n_plants)
    cell_index: np.ndarray             # rows -> global cell row ids
    plant_index: np.ndarray            # cols -> global plant ids
    lambda_km: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.matrix.shape

    @property
    def nnz(self) -> int:
        return self.matrix.nnz

    @property
    def density(self) -> float:
        rows, cols = self.matrix.shape
        return self.nnz / (rows * cols) if rows and cols else 0.0


def build_kernel(
    cell_lat: np.ndarray, cell_lon: np.ndarray,
    plant_lat: np.ndarray, plant_lon: np.ndarray,
    *,
    cell_index: np.ndarray | None = None,
    plant_index: np.ndarray | None = None,
    lambda_km: float = DEFAULT_LAMBDA_KM,
    k_nearest: int = DEFAULT_K_NEAREST,
    near_km: float = DEFAULT_NEAR_KM,
) -> Kernel:
    """Build K for one region. Callers pass only that region's cells and plants,
    which is how the no-crossing constraint is enforced -- structurally, rather
    than as a penalty the solver could trade away."""
    n_cells, n_plants = len(cell_lat), len(plant_lat)
    if n_cells == 0 or n_plants == 0:
        return Kernel(sparse.csr_matrix((n_cells, n_plants)),
                      cell_index if cell_index is not None else np.arange(n_cells),
                      plant_index if plant_index is not None else np.arange(n_plants),
                      lambda_km)

    cells_xyz = to_ecef(cell_lat, cell_lon)
    plants_xyz = to_ecef(plant_lat, plant_lon)
    tree = cKDTree(plants_xyz)

    cutoff_km = 5.0 * lambda_km
    # Chord radius corresponding to the great-circle cutoff.
    chord_cutoff = 2 * EARTH_RADIUS_KM * np.sin(min(cutoff_km, np.pi * EARTH_RADIUS_KM)
                                                / (2 * EARTH_RADIUS_KM))
    chord_near = 2 * EARTH_RADIUS_KM * np.sin(min(near_km, cutoff_km)
                                              / (2 * EARTH_RADIUS_KM))

    k = min(k_nearest, n_plants)
    knn_d, knn_j = tree.query(cells_xyz, k=k, workers=-1)
    if k == 1:
        knn_d, knn_j = knn_d[:, None], knn_j[:, None]

    radius_j = tree.query_ball_point(cells_xyz, r=chord_near, workers=-1)

    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    for i in range(n_cells):
        near = knn_j[i][knn_d[i] <= chord_cutoff]
        combined = np.union1d(near, np.asarray(radius_j[i], dtype=np.int64))
        if combined.size == 0:
            # Nothing within the cutoff: fall back to the single nearest plant so
            # the cell still gets served. Leaving it empty would silently drop
            # its demand from the region's balance.
            combined = knn_j[i][:1]
        rows.append(np.full(combined.size, i, dtype=np.int64))
        cols.append(combined)

    row_idx = np.concatenate(rows)
    col_idx = np.concatenate(cols)
    chord = np.linalg.norm(cells_xyz[row_idx] - plants_xyz[col_idx], axis=1)
    great_circle = chord_to_great_circle(chord)
    values = np.exp(-great_circle / lambda_km)

    matrix = sparse.csr_matrix(
        (values, (row_idx, col_idx)), shape=(n_cells, n_plants))
    return Kernel(
        matrix,
        cell_index if cell_index is not None else np.arange(n_cells),
        plant_index if plant_index is not None else np.arange(n_plants),
        lambda_km,
    )
