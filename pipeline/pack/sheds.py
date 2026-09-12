"""Pack solved sheds into static files a browser can fetch one at a time.

The many-to-many join looks alarming but is bounded: cell-major and plant-major
are the same sparse matrix in two orderings, so total size is nnz x bytes-per-
entry regardless of how many plants there are. Precomputing every shed therefore
costs the same as precomputing only the large ones, and every plant stays
clickable.

Layout:

    cells.bin   uint64[]  H3 cell ids, in the order everything else indexes into
    sheds.bin   concatenated per-plant records, fetched by HTTP Range
    sheds.idx.json  plant id -> {offset, length, stats}

Storing a global cell array once and referring to it by uint32 index costs 5
bytes per entry instead of 9, and spares the client any varint decoding. For
resolution 6 the index would want delta+varint compression; at the resolutions
shipped here the simpler format is worth more than the bytes it costs.

Pruning is deliberately asymmetric -- top-K per cell *and* top-N per plant. The
second clause is what stops a small plant vanishing: a 5 MW diesel unit never
makes any cell's top 12, and without it would have no shed at all.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import sparse

MAGIC = b"OGSH"
VERSION = 1

#: Per cell, keep this many plants; per plant, this many cells.
TOP_PLANTS_PER_CELL = 12
TOP_CELLS_PER_PLANT = 2000
#: Shares below this contribute nothing visible and cost real bytes.
MIN_SHARE = 0.002


@dataclass
class PackStats:
    plants: int = 0
    cells: int = 0
    entries_before: int = 0
    entries_after: int = 0
    bytes_sheds: int = 0
    bytes_cells: int = 0
    largest_shed_cells: int = 0
    median_shed_cells: int = 0
    population_served: float = 0.0
    population_total: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def population_conservation(self) -> float:
        """Sum of per-plant population-served over world population.

        Should approach 1: pi sums to 1 across plants for every served cell, so
        summing pi-weighted population over all plants must recover the
        population itself. Anything well below 1 means demand is going unserved
        or pruning is discarding more than intended -- a genuine check on the
        allocation, not a cosmetic one.
        """
        return self.population_served / self.population_total if self.population_total else 0.0

    @property
    def pruned_fraction(self) -> float:
        if not self.entries_before:
            return 0.0
        return 1 - self.entries_after / self.entries_before


def prune(shares_by_cell: sparse.csr_matrix,
          transport: sparse.csr_matrix) -> sparse.csr_matrix:
    """Drop entries that cannot matter, keeping every plant non-empty.

    Operates on pi (cell-major shares) for the per-cell rule and on T (GWh) for
    the per-plant rule, because "this plant's biggest destinations" is a question
    about energy, not about another cell's mix.
    """
    keep = sparse.lil_matrix(shares_by_cell.shape, dtype=bool)

    csr = shares_by_cell.tocsr()
    for i in range(csr.shape[0]):
        lo, hi = csr.indptr[i], csr.indptr[i + 1]
        if lo == hi:
            continue
        data, cols = csr.data[lo:hi], csr.indices[lo:hi]
        order = np.argsort(data)[::-1][:TOP_PLANTS_PER_CELL]
        order = order[data[order] >= MIN_SHARE]
        if order.size:
            keep[i, cols[order]] = True

    # Per-plant clause: guarantee a shed even for plants no cell ranks highly.
    csc = transport.tocsc()
    for j in range(csc.shape[1]):
        lo, hi = csc.indptr[j], csc.indptr[j + 1]
        if lo == hi:
            continue
        data, rows = csc.data[lo:hi], csc.indices[lo:hi]
        order = np.argsort(data)[::-1][:TOP_CELLS_PER_PLANT]
        keep[rows[order], j] = True

    mask = keep.tocsr()
    out = shares_by_cell.multiply(mask).tocsr()
    out.eliminate_zeros()
    return out


def write(
    out_dir: Path,
    cells: np.ndarray,
    plant_ids: list[str],
    shares_by_plant: sparse.csc_matrix,
    shares_by_cell: sparse.csr_matrix,
    transport: sparse.csr_matrix,
    population: np.ndarray,
) -> PackStats:
    """Write cells.bin, sheds.bin and sheds.idx.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = PackStats(plants=len(plant_ids), cells=len(cells))

    (out_dir / "cells.bin").write_bytes(cells.astype("<u8").tobytes())
    stats.bytes_cells = (out_dir / "cells.bin").stat().st_size

    csc = shares_by_plant.tocsc()
    # pi in column form. The two share matrices answer different questions and
    # are not interchangeable: phi says where this plant's output goes (and sums
    # to 1 down a column), pi says what fraction of a cell's demand this plant
    # supplies. Population served is a question about pi -- weighting a cell's
    # people by phi would give a weighted average cell size, not a headcount.
    pi = shares_by_cell.tocsc()
    energy = transport.tocsc()
    stats.entries_before = csc.nnz

    index: dict[str, dict] = {}
    sizes: list[int] = []
    offset = 0

    with (out_dir / "sheds.bin").open("wb") as fh:
        for j, pid in enumerate(plant_ids):
            lo, hi = csc.indptr[j], csc.indptr[j + 1]
            rows, phi = csc.indices[lo:hi], csc.data[lo:hi]
            if rows.size:
                order = np.argsort(phi)[::-1][:TOP_CELLS_PER_PLANT]
                rows, phi = rows[order], phi[order]
                # Sorted cell order keeps the client's work predictable and
                # leaves the door open to delta coding later.
                order = np.argsort(rows)
                rows, phi = rows[order], phi[order]

            # sqrt companding: shed shares are heavily skewed, and a linear
            # uint8 would quantise almost every cell in a large shed to 0.
            quantised = np.clip(np.round(255 * np.sqrt(phi)), 0, 255).astype(np.uint8)
            visible = quantised > 0
            rows, phi, quantised = rows[visible], phi[visible], quantised[visible]

            gwh = float(energy[:, j].sum())

            # pi restricted to this plant's column, aligned to `rows`.
            plo, phi_hi = pi.indptr[j], pi.indptr[j + 1]
            pi_rows, pi_vals = pi.indices[plo:phi_hi], pi.data[plo:phi_hi]
            lookup = dict(zip(pi_rows.tolist(), pi_vals.tolist()))
            pi_here = np.array([lookup.get(int(r), 0.0) for r in rows], dtype=np.float64) \
                if rows.size else np.empty(0)

            # Demand-weighted: the honest number. A cell half-supplied by this
            # plant contributes half its people.
            pop = float((population[rows] * pi_here).sum()) if rows.size else 0.0
            # Headcount above a visibility threshold: the bigger, more quotable
            # number, which means something quite different. Both are shipped and
            # both are labelled, because publishing only the second would mislead.
            touched = float(population[rows][pi_here > 0.0].sum()) if rows.size else 0.0

            record = (
                MAGIC
                + struct.pack("<BBHI", VERSION, 0, 0, rows.size)
                + struct.pack("<fff", gwh, pop, touched)
                + rows.astype("<u4").tobytes()
                + quantised.tobytes()
            )
            fh.write(record)

            index[pid] = {"o": offset, "n": len(record), "c": int(rows.size),
                          "gwh": round(gwh, 1), "pop": round(pop),
                          "reach": round(touched)}
            offset += len(record)
            sizes.append(int(rows.size))
            stats.entries_after += int(rows.size)

    stats.population_served = sum(v["pop"] for v in index.values())
    stats.population_total = float(population.sum())
    if stats.population_conservation < 0.9:
        stats.notes.append(
            f"POPULATION CONSERVATION: per-plant population served sums to "
            f"{stats.population_conservation:.1%} of world population. Shares per "
            "cell should sum to 1, so a large shortfall means demand is unserved "
            "or pruning is too aggressive."
        )

    stats.bytes_sheds = (out_dir / "sheds.bin").stat().st_size
    if sizes:
        stats.largest_shed_cells = max(sizes)
        stats.median_shed_cells = int(np.median(sizes))
    empty = sum(1 for s in sizes if s == 0)
    if empty:
        stats.notes.append(
            f"{empty:,} plants have an empty shed: their output could not be "
            "placed inside their own synchronous region."
        )

    (out_dir / "sheds.idx.json").write_text(json.dumps(index, separators=(",", ":")))
    return stats
