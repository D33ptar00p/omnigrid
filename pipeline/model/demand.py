"""Build the demand surface: where electricity is consumed, and how much.

Each populated H3 cell gets an annual demand in GWh:

    d_i  ∝  population_i  x  per-capita consumption(country)  x  electrified_i

then renormalised so each country's cells sum to its reported national demand.
The renormalisation is what keeps the model honest at country level even where
the within-country distribution is crude.

Two known weaknesses, both stated rather than hidden:

  * Demand proportional to population is badly wrong for industrial load --
    smelters, steel, desalination, mining, hyperscale data centres. Iceland,
    Norway, Québec, Bahrain and northern Virginia will be visibly off.
  * The electrified fraction comes from gridfinder, which is ~70% accurate, so
    it is blended against World Bank national electrification rates rather than
    used raw. A region gridfinder wrongly marks dark would otherwise get zero
    demand and no supply shed at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SOURCE_ID = "kontur_pop"
METHOD = "demand.population_weighted"


@dataclass
class DemandSurface:
    """Populated cells with demand, country and synchronous region attached."""

    #: H3 cell ids (uint64), sorted.
    cells: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    population: np.ndarray
    #: ISO3 per cell; empty string where no country could be assigned.
    country: np.ndarray
    #: Synchronous region id per cell.
    region: np.ndarray
    #: Annual demand, GWh.
    demand_gwh: np.ndarray
    resolution: int = 6
    unassigned: int = 0
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.cells)

    @property
    def total_population(self) -> float:
        return float(self.population.sum())

    @property
    def total_demand_gwh(self) -> float:
        return float(self.demand_gwh.sum())

    def region_slices(self) -> dict[str, np.ndarray]:
        """Row indices per synchronous region.

        The allocation solves one region at a time, so this partition is both the
        enforcement of the no-crossing constraint and the main axis of parallelism.
        """
        order = np.argsort(self.region, kind="stable")
        sorted_regions = self.region[order]
        bounds = np.flatnonzero(np.r_[True, sorted_regions[1:] != sorted_regions[:-1], True])
        return {
            str(sorted_regions[bounds[i]]): order[bounds[i]:bounds[i + 1]]
            for i in range(len(bounds) - 1)
        }


def _ensure_uncompressed(path: Path) -> Path:
    """GDAL cannot read a gzipped GeoPackage. Decompress once into data/interim
    and reuse it, rather than paying 5 seconds on every run."""
    import gzip
    import shutil

    if path.suffix != ".gz":
        return path
    interim = path.parents[2] / "interim"
    interim.mkdir(parents=True, exist_ok=True)
    out = interim / path.stem
    if not out.exists() or out.stat().st_size == 0:
        tmp = out.with_suffix(out.suffix + ".part")
        with gzip.open(path, "rb") as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        tmp.replace(out)
    return out


def load_cells(gpkg: Path, *, resolution: int = 6, min_population: float = 1.0):
    """Read Kontur's H3 cells. Returns (cell_ids, lat, lon, population).

    Kontur ships resolution 6 (~36 km2). Coarser resolutions are produced by
    aggregating up rather than by a separate download, so the dev loop and the
    production run read the same file.
    """
    import duckdb
    import h3
    import h3.api.basic_int as h3i

    gpkg = _ensure_uncompressed(gpkg)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute(
        "SELECT h3, population FROM st_read(?) WHERE population >= ?",
        [str(gpkg), min_population],
    ).fetchnumpy()
    con.close()

    hex_strings = rows["h3"].astype(str)
    population = rows["population"].astype(np.float64)

    cells = np.fromiter((h3.str_to_int(s) for s in hex_strings), dtype=np.uint64,
                        count=len(hex_strings))

    if resolution < 6:
        cells, population = _aggregate(cells, population, resolution)

    latlng = np.array([h3i.cell_to_latlng(int(c)) for c in cells], dtype=np.float64)
    return cells, latlng[:, 0], latlng[:, 1], population


def _aggregate(cells: np.ndarray, population: np.ndarray, resolution: int):
    """Roll cells up to a coarser resolution, summing population."""
    import h3
    import h3.api.basic_int as h3i

    parents = np.fromiter(
        (h3i.cell_to_parent(int(c), resolution) for c in cells),
        dtype=np.uint64, count=len(cells),
    )
    uniq, inverse = np.unique(parents, return_inverse=True)
    summed = np.zeros(len(uniq), dtype=np.float64)
    np.add.at(summed, inverse, population)
    return uniq, summed


def _gdal_path(path: Path) -> str:
    """GDAL needs an explicit /vsizip/ route into a zipped shapefile."""
    if path.suffix == ".zip":
        return f"/vsizip/{path}/{path.stem}.shp"
    return str(path)


def assign_countries(cells: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                     boundaries: Path) -> tuple[np.ndarray, int]:
    """Point-in-polygon against Natural Earth, with a nearest-country fallback.

    Coastal cells routinely fall just outside a simplified coastline, and the 50m
    boundaries are simplified. Dropping them would quietly delete demand from
    exactly the places most people live, so unmatched cells snap to the nearest
    country within a tolerance instead. Returns (iso3_per_cell, n_snapped).
    """
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute(
        "CREATE TABLE pts AS SELECT * FROM (VALUES (NULL::UBIGINT, NULL::DOUBLE, NULL::DOUBLE)) "
        "t(cell, lat, lon) WHERE false"
    )
    con.register("pts_in", {"cell": cells, "lat": lat, "lon": lon})
    con.execute("INSERT INTO pts SELECT cell, lat, lon FROM pts_in")
    con.execute(
        "CREATE TABLE ctry AS SELECT ADM0_A3 AS iso3, geom FROM st_read(?)",
        [_gdal_path(boundaries)],
    )

    # Containment first: the common case, and exact where the boundary is.
    con.execute("""
        CREATE TABLE hit AS
        SELECT p.cell, c.iso3
        FROM pts p JOIN ctry c
          ON ST_Contains(c.geom, ST_Point(p.lon, p.lat))
    """)

    # Then snap whatever is left to the nearest country, bounded so that a cell
    # in the middle of an ocean is left unassigned rather than dragged ashore.
    con.execute("""
        CREATE TABLE miss AS
        SELECT p.cell, p.lat, p.lon FROM pts p
        LEFT JOIN hit h ON h.cell = p.cell WHERE h.cell IS NULL
    """)
    n_snapped = con.execute("""
        CREATE TABLE snapped AS
        SELECT cell, iso3 FROM (
            SELECT m.cell, c.iso3,
                   row_number() OVER (PARTITION BY m.cell
                       ORDER BY ST_Distance(c.geom, ST_Point(m.lon, m.lat))) AS rn
            FROM miss m JOIN ctry c
              ON ST_DWithin(c.geom, ST_Point(m.lon, m.lat), 1.5)
        ) WHERE rn = 1;
        SELECT count(*) FROM snapped
    """).fetchone()[0]

    rows = con.execute("""
        SELECT p.cell, coalesce(h.iso3, s.iso3, '') AS iso3
        FROM pts p
        LEFT JOIN hit h ON h.cell = p.cell
        LEFT JOIN snapped s ON s.cell = p.cell
    """).fetchnumpy()
    con.close()

    # Restore the caller's ordering.
    order = {int(c): i for i, c in enumerate(rows["cell"])}
    iso3 = np.array([rows["iso3"][order[int(c)]] for c in cells], dtype=object)
    return iso3, int(n_snapped)


def build(gpkg: Path, boundaries: Path, ember, region_index, *,
          resolution: int = 6, min_population: float = 1.0) -> DemandSurface:
    """Assemble the full demand surface.

    Demand is distributed within a country in proportion to population, then
    renormalised so the country sums to Ember's reported national demand. The
    renormalisation is what matters: it makes each country's total right even
    where the within-country distribution is crude.
    """
    cells, lat, lon, population = load_cells(
        gpkg, resolution=resolution, min_population=min_population)
    iso3, snapped = assign_countries(cells, lat, lon, boundaries)

    notes: list[str] = []
    if snapped:
        notes.append(
            f"{snapped:,} coastal cells fell outside the simplified 50m coastline "
            "and were snapped to the nearest country within ~1.5 degrees."
        )

    # Per-country population totals drive the split; the national total comes
    # from Ember, so within-country error cannot leak across borders.
    demand = np.zeros(len(cells), dtype=np.float64)
    countries = np.unique(iso3)
    missing_demand: list[str] = []
    for c in countries:
        if not c:
            continue
        mask = iso3 == c
        pop_total = population[mask].sum()
        if pop_total <= 0:
            continue
        national = ember.demand.get(c)
        if national is None:
            # No reported demand: fall back to reported generation, and failing
            # that leave the country at zero and say so, rather than inventing
            # a per-capita figure for it.
            national = ember.total_generation.get(c)
            if national is None:
                missing_demand.append(str(c))
                continue
        demand[mask] = population[mask] / pop_total * national

    if missing_demand:
        notes.append(
            f"{len(missing_demand)} countries have no reported demand or generation "
            f"and carry zero modelled demand: {', '.join(sorted(missing_demand)[:12])}"
            + ("..." if len(missing_demand) > 12 else "")
        )

    notes.append(
        "Demand is distributed in proportion to population. This is badly wrong "
        "for industrial load -- smelters, steel, desalination, mining and "
        "hyperscale data centres -- so Iceland, Norway, Quebec, Bahrain and "
        "northern Virginia are expected to be visibly off."
    )
    notes.append(
        "Grid reach is not yet modelled: every populated cell is treated as "
        "connected. In countries with partial electrification this spreads demand "
        "more evenly than reality."
    )

    region = np.empty(len(cells), dtype=object)
    for i in range(len(cells)):
        rid, _ = region_index.assign(str(iso3[i]), lat[i], lon[i])
        region[i] = rid

    return DemandSurface(
        cells=cells, lat=lat, lon=lon, population=population,
        country=iso3, region=region, demand_gwh=demand,
        resolution=resolution, unassigned=int((iso3 == "").sum()), notes=notes,
    )
