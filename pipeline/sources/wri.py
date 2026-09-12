"""Read WRI Global Power Plant Database v1.3.0.

Unmaintained since 2021, so it is never the primary source. Two jobs:

  1. cross-check -- its `estimated_generation_gwh` is an independent estimate to
     compare our Ember-calibrated one against, and divergence is a build artefact
     rather than something quietly reconciled;
  2. degraded fallback -- lets a fresh clone build a real map before anyone has
     hand-fetched the form-gated GEM trackers.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Iterator

from pipeline.provenance import Cited, measured
from pipeline.schema import (
    Asset, AssetKind, Fuel, Status, UnknownFuel, is_non_generating, parse_fuel,
)

SOURCE_ID = "wri_gppd"
CSV_NAME = "global_power_plant_database.csv"

#: Most recent estimate year available in v1.3.0.
EST_YEAR = 2017
#: Reported (not estimated) generation, newest first.
REPORTED_YEARS = (2019, 2018, 2017, 2016, 2015, 2014, 2013)


class Skipped(Exception):
    """A row we deliberately drop, with the reason preserved for the build report."""


def _float(row: dict[str, str], key: str) -> float | None:
    v = (row.get(key) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _row_to_asset(row: dict[str, str]) -> Asset:
    raw_fuel = (row.get("primary_fuel") or "").strip()
    if is_non_generating(raw_fuel):
        raise Skipped(f"non-generating ({raw_fuel})")

    lat, lon = _float(row, "latitude"), _float(row, "longitude")
    if lat is None or lon is None:
        raise Skipped("no coordinates")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise Skipped(f"coordinates out of range ({lat}, {lon})")

    capacity = _float(row, "capacity_mw")
    if capacity is None or capacity <= 0:
        raise Skipped("no capacity")

    fuel = parse_fuel(raw_fuel)  # raises UnknownFuel -- caught and counted by the caller

    # Prefer reported generation over WRI's own model where both exist.
    generation: Cited[float] | None = None
    for yr in REPORTED_YEARS:
        if (g := _float(row, f"generation_gwh_{yr}")) is not None:
            generation = measured(g, SOURCE_ID)
            break
    else:
        if (g := _float(row, f"estimated_generation_gwh_{EST_YEAR}")) is not None:
            # WRI's estimate, not ours: measured *from WRI's perspective*, and we
            # keep it distinct from our own derived figure so the two can be compared.
            generation = measured(g, SOURCE_ID)

    year = _float(row, "commissioning_year")
    owner = (row.get("owner") or "").strip()

    return Asset(
        id=f"wri:{row['gppd_idnr']}",
        kind=AssetKind.GENERATION,
        name=(row.get("name") or "").strip() or row["gppd_idnr"],
        country=(row.get("country") or "").strip(),
        lat=lat,
        lon=lon,
        fuel=measured(fuel, SOURCE_ID),
        # v1.3.0 has no status column; every row is treated as operating as of its
        # capacity year. Recorded as measured-from-WRI so the assumption is visible.
        status=measured(Status.OPERATING, SOURCE_ID),
        capacity_mw=measured(capacity, SOURCE_ID),
        owner=measured(owner, SOURCE_ID) if owner else None,
        commissioned=measured(int(year), SOURCE_ID) if year else None,
        generation_gwh=generation,
    )


def read(archive: Path) -> tuple[list[Asset], dict[str, int]]:
    """Parse the zip into assets plus a tally of what was dropped and why.

    The tally is returned rather than logged because silently dropping rows is how
    a dataset quietly loses a country.
    """
    assets: list[Asset] = []
    skipped: dict[str, int] = {}

    def note(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    with zipfile.ZipFile(archive) as z, z.open(CSV_NAME) as fh:
        for row in csv.DictReader(io.TextIOWrapper(fh, "utf-8")):
            try:
                assets.append(_row_to_asset(row))
            except Skipped as e:
                note(str(e).split(" (")[0])
            except UnknownFuel as e:
                # Not swallowed: surfaced so the taxonomy gets fixed.
                note(f"UNMAPPED FUEL: {e}")
    return assets, skipped


def iter_fuel_values(archive: Path) -> Iterator[str]:
    with zipfile.ZipFile(archive) as z, z.open(CSV_NAME) as fh:
        for row in csv.DictReader(io.TextIOWrapper(fh, "utf-8")):
            yield (row.get("primary_fuel") or "").strip()
