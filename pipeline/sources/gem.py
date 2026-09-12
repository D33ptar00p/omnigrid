"""Read the Global Energy Monitor Global Integrated Power Tracker.

183,125 generating units across 145,396 locations, every one with coordinates —
about five times the coverage of WRI's database and actively maintained, which is
why this is the primary global source and WRI is only a fallback.

The file is unit-level: one row per turbine, phase or block. Units are grouped
into plants by GEM's own location id, so a six-unit coal station reads as one
plant rather than six dots stacked on the same pixel.

Downloading it requires a name and email on a web form, so it cannot be fetched
by script and is vendored into data/raw/gem/ by hand.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from pipeline.provenance import measured
from pipeline.schema import Asset, AssetKind, Fuel, Status, UnknownFuel

SOURCE_ID = "gem_gipt"
SHEET = "Power facilities"

#: GEM's `Type` column -> our taxonomy. "oil/gas" is resolved further by the
#: fuel-classification column below, since the two burn very differently.
TYPES: dict[str, Fuel] = {
    "coal": Fuel.COAL,
    "utility-scale solar": Fuel.SOLAR,
    "wind": Fuel.WIND,
    "hydropower": Fuel.HYDRO,
    "bioenergy": Fuel.BIOENERGY,
    "nuclear": Fuel.NUCLEAR,
    "geothermal": Fuel.GEOTHERMAL,
}

#: `Fuel classification (oil/gas only)`. "Multi Fuel" plants can burn either;
#: they are counted as gas, which is what they run on in practice, and the raw
#: classification is kept on the asset so the choice is visible.
OIL_GAS: dict[str, Fuel] = {
    "Gas": Fuel.GAS,
    "LNG only": Fuel.GAS,
    "Multi Fuel": Fuel.GAS,
    "Oil": Fuel.OIL,
}

STATUSES: dict[str, Status] = {
    "operating": Status.OPERATING,
    "construction": Status.CONSTRUCTION,
    "pre-construction": Status.ANNOUNCED,
    "announced": Status.ANNOUNCED,
    "retired": Status.RETIRED,
    "mothballed": Status.MOTHBALLED,
    "cancelled": Status.CANCELLED,
    "shelved": Status.CANCELLED,
}

#: Ranked worst-to-best. A plant with any operating unit is operating.
_STATUS_RANK = [
    Status.CANCELLED, Status.ANNOUNCED, Status.RETIRED,
    Status.MOTHBALLED, Status.CONSTRUCTION, Status.OPERATING,
]


def _status(raw: str | None) -> Status:
    """Map GEM's status, including its "- inferred N y" suffixes."""
    if not raw:
        return Status.ANNOUNCED
    key = str(raw).split(" - ")[0].strip().lower()
    return STATUSES.get(key, Status.ANNOUNCED)


def _fuel(type_: str, classification: str | None) -> Fuel:
    if type_ == "oil/gas":
        if not classification:
            return Fuel.GAS
        try:
            return OIL_GAS[str(classification).strip()]
        except KeyError:
            raise UnknownFuel(
                f"unmapped GEM oil/gas classification {classification!r}; add it "
                "to OIL_GAS rather than letting it fall through"
            ) from None
    try:
        return TYPES[type_]
    except KeyError:
        raise UnknownFuel(
            f"unmapped GEM Type {type_!r}; add it to TYPES in pipeline/sources/gem.py"
        ) from None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    f = _float(value)
    return int(f) if f is not None else None


def _first_party(value: Any) -> str | None:
    """GEM lists owners as "Company A [60%]; Company B [40%]". Take the first."""
    if not value:
        return None
    text = str(value).split(";")[0]
    return text.split("[")[0].strip() or None


@dataclass
class _Group:
    """Units sharing a GEM location: one plant."""

    name: str = ""
    country: str = ""
    fuel: Fuel | None = None
    lat: float = 0.0
    lon: float = 0.0
    capacity_mw: float = 0.0
    status: Status = Status.CANCELLED
    operator: str | None = None
    owner: str | None = None
    start_year: int | None = None
    retired_year: int | None = None
    units: int = 0
    wiki: str | None = None
    #: Capacity per fuel, so a mixed site is attributed to its largest fuel.
    by_fuel: dict[Fuel, float] = field(default_factory=lambda: defaultdict(float))


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb[SHEET]
    stream = sheet.iter_rows(values_only=True)
    header = [str(c).strip() if c else "" for c in next(stream)]
    for row in stream:
        if row and row[0]:
            yield dict(zip(header, row))
    wb.close()


def read(path: Path) -> tuple[list[Asset], dict[str, int]]:
    """Parse the workbook into plant-level assets, plus a tally of what was skipped."""
    groups: dict[str, _Group] = {}
    skipped: dict[str, int] = {}

    def note(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in _rows(path):
        type_ = (row.get("Type") or "").strip()
        lat, lon = _float(row.get("Latitude")), _float(row.get("Longitude"))
        if lat is None or lon is None:
            note("no coordinates")
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            note("coordinates out of range")
            continue

        try:
            fuel = _fuel(type_, row.get("Fuel classification (oil/gas only)"))
        except UnknownFuel as e:
            note(f"UNMAPPED: {e}")
            continue

        key = str(row.get("GEM location ID") or
                  f"{row.get('Plant / Project name')}|{row.get('Country/area')}")
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group(
                name=str(row.get("Plant / Project name") or "Unnamed").strip(),
                country=str(row.get("Country/area") or "").strip(),
                lat=lat, lon=lon,
                wiki=row.get("GEM.Wiki URL"),
            )

        capacity = _float(row.get("Capacity (MW)")) or 0.0
        group.capacity_mw += capacity
        group.by_fuel[fuel] += capacity
        group.units += 1

        status = _status(row.get("Status"))
        if _STATUS_RANK.index(status) > _STATUS_RANK.index(group.status):
            group.status = status

        group.operator = group.operator or _first_party(row.get("Operator(s)"))
        group.owner = group.owner or _first_party(row.get("Owner(s)"))

        if (year := _int(row.get("Start year"))) is not None:
            group.start_year = year if group.start_year is None else min(group.start_year, year)
        if (year := _int(row.get("Retired year"))) is not None:
            group.retired_year = year if group.retired_year is None else max(
                group.retired_year, year)

    assets: list[Asset] = []
    for key, g in groups.items():
        # A site with several fuels is attributed to whichever contributes most
        # capacity, rather than to whichever unit happened to be read first.
        fuel = max(g.by_fuel, key=g.by_fuel.get) if g.by_fuel else None
        if fuel is None:
            note("no fuel")
            continue
        extra = {}
        if g.units > 1:
            extra["units"] = measured(g.units, SOURCE_ID)
        if g.wiki:
            extra["wiki_url"] = measured(str(g.wiki), SOURCE_ID)

        assets.append(Asset(
            id=f"gem:{key}",
            kind=AssetKind.GENERATION,
            name=g.name,
            country=g.country,
            lat=round(g.lat, 5), lon=round(g.lon, 5),
            fuel=measured(fuel, SOURCE_ID),
            status=measured(g.status, SOURCE_ID),
            capacity_mw=measured(round(g.capacity_mw, 2), SOURCE_ID)
            if g.capacity_mw > 0 else None,
            owner=measured(g.owner or g.operator, SOURCE_ID)
            if (g.owner or g.operator) else None,
            commissioned=measured(g.start_year, SOURCE_ID) if g.start_year else None,
            retired=measured(g.retired_year, SOURCE_ID) if g.retired_year else None,
            extra=extra,
        ))
    return assets, skipped
