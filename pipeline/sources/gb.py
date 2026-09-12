"""Great Britain: measured generation and the published network it feeds.

Everything here is observed or published. Nothing is modelled.

  * Elexon BM Unit reference -- what each generating unit is, and for embedded
    units, `gspGroupId`: the published code for the distribution region it feeds.
  * Elexon B1610 -- settlement-grade metered output per unit, half-hourly. This
    is the volume the unit is actually settled on, not an estimate.
  * NESO DNO licence areas -- the 14 real distribution regions. Their `Name`
    field carries the same codes as Elexon's gspGroupId, which is what makes the
    generator-to-region link a published fact rather than an inference.

The honest limit of this data: only *embedded* generators have a region. A
transmission-connected plant -- Drax, Hinkley, the large offshore wind farms --
feeds the national transmission system and therefore serves all of GB. There is
no measured "Drax serves Yorkshire" because it is not true.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from pipeline.provenance import Cited, measured
from pipeline.schema import Fuel

BMU_SOURCE = "elexon_bmu"
B1610_SOURCE = "elexon_b1610"
DNO_SOURCE = "neso_dno_areas"

#: Elexon fuel types -> our taxonomy. Total, like the global one: an unmapped
#: value raises rather than silently becoming OTHER.
FUEL_TYPES: dict[str, Fuel] = {
    "CCGT": Fuel.GAS, "OCGT": Fuel.GAS, "COAL": Fuel.COAL, "OIL": Fuel.OIL,
    "NUCLEAR": Fuel.NUCLEAR, "WIND": Fuel.WIND, "NPSHYD": Fuel.HYDRO,
    "BIOMASS": Fuel.BIOENERGY, "OTHER": Fuel.OTHER,
}

#: Pumped storage moves energy in time, it does not generate it. Counting it as
#: generation double-counts the electricity used to fill it.
STORAGE_TYPES = {"PS"}

#: Interconnectors import from other countries; they are not GB generation.
#: A single physical link (BritNed, IFA, Viking) is represented by many
#: accounting BM Units -- "BritNed ND Dem Account" and siblings -- so they are
#: grouped by interconnectorId rather than counted as units. Summing their
#: declared capacities would claim ~700 GW of interconnection for a country
#: that has roughly 10.
INTERCONNECTOR_PREFIX = "INT"


class Connection(str, Enum):
    """How a unit reaches consumers. This is the crux of the whole map."""

    TRANSMISSION = "transmission"
    EMBEDDED = "embedded"
    INTERCONNECTOR = "interconnector"

    @property
    def has_published_region(self) -> bool:
        """Only embedded units carry a distribution region in the source data."""
        return self is Connection.EMBEDDED

    @property
    def description(self) -> str:
        return {
            Connection.TRANSMISSION:
                "Transmission-connected — feeds the GB national grid. No single "
                "region: its output serves Great Britain as a whole.",
            Connection.EMBEDDED:
                "Embedded in a distribution network — Elexon publishes the "
                "region this unit feeds.",
            Connection.INTERCONNECTOR:
                "Interconnector — imports and exports across a subsea link, "
                "rather than generating.",
        }[self]


#: Elexon BM Unit type codes. T is transmission; the rest connect at
#: distribution level and carry a gspGroupId.
EMBEDDED_TYPES = {"E", "S", "G", "V"}


class UnknownFuelType(ValueError):
    """An Elexon fuel type we have not mapped. Fatal: fix the table."""


@dataclass(slots=True)
class Unit:
    """One Balancing Mechanism Unit."""

    bm_unit: str
    name: str
    fuel: Cited[Fuel] | None
    connection: Connection
    capacity_mw: Cited[float] | None = None
    operator: Cited[str] | None = None
    #: Published GSP group, e.g. "_N". Present only for embedded units.
    gsp_group_id: Cited[str] | None = None
    gsp_group_name: Cited[str] | None = None
    #: Metered output in MWh for the settlement period(s) loaded.
    metered_mwh: Cited[float] | None = None
    interconnector_id: str | None = None

    @property
    def is_generation(self) -> bool:
        return self.connection is not Connection.INTERCONNECTOR

    @property
    def fuel_declared(self) -> bool:
        """Elexon does not declare a fuel type for every unit. Shown as
        'not declared' rather than guessed."""
        return self.fuel is not None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "bm_unit": self.bm_unit,
            "name": self.name,
            "connection": self.connection.value,
            "connection_note": self.connection.description,
        }
        for key in ("fuel", "capacity_mw", "operator", "gsp_group_id",
                    "gsp_group_name", "metered_mwh"):
            if (v := getattr(self, key)) is not None:
                out[key] = v.to_json()
        return out


@dataclass
class Region:
    """One DNO licence area."""

    code: str          # matches Elexon gspGroupId, e.g. "_A"
    area: str          # "East England"
    dno: str           # "UKPN"
    dno_full: str
    geometry: dict[str, Any]


@dataclass
class GBData:
    units: list[Unit] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    settlement_date: str = ""
    settlement_period: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def generation_units(self) -> list[Unit]:
        return [u for u in self.units if u.is_generation]

    def by_connection(self, kind: Connection) -> list[Unit]:
        return [u for u in self.units if u.connection is kind]

    @property
    def interconnectors(self) -> dict[str, list[Unit]]:
        """Physical links, each grouped from its many accounting BM Units."""
        out: dict[str, list[Unit]] = {}
        for u in self.by_connection(Connection.INTERCONNECTOR):
            if u.interconnector_id:
                out.setdefault(u.interconnector_id, []).append(u)
        return out


def _classify(row: dict[str, Any]) -> Connection:
    fuel_type = (row.get("fuelType") or "").upper()
    if fuel_type.startswith(INTERCONNECTOR_PREFIX) or row.get("interconnectorId"):
        return Connection.INTERCONNECTOR
    if row.get("bmUnitType") in EMBEDDED_TYPES and row.get("gspGroupId"):
        return Connection.EMBEDDED
    return Connection.TRANSMISSION


def _float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def read_units(path: Path) -> tuple[list[Unit], dict[str, int]]:
    """Parse the BM Unit reference dump. Returns (units, skipped-by-reason)."""
    raw = json.loads(path.read_text())
    rows = raw if isinstance(raw, list) else raw.get("data", [])
    units: list[Unit] = []
    skipped: dict[str, int] = {}

    def note(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in rows:
        bm_unit = row.get("elexonBmUnit") or row.get("nationalGridBmUnit")
        if not bm_unit:
            note("no BM unit id")
            continue

        fuel_type = (row.get("fuelType") or "").upper()
        connection = _classify(row)

        capacity = _float(row.get("generationCapacity"))

        fuel: Cited[Fuel] | None = None
        if connection is not Connection.INTERCONNECTOR:
            if fuel_type in STORAGE_TYPES:
                note("pumped storage (not generation)")
                continue
            if fuel_type and fuel_type not in FUEL_TYPES:
                raise UnknownFuelType(
                    f"unmapped Elexon fuelType {fuel_type!r} on {bm_unit}; add it to "
                    "FUEL_TYPES rather than letting it fall through"
                )
            if fuel_type:
                fuel = measured(FUEL_TYPES[fuel_type], BMU_SOURCE)
            elif not capacity or capacity <= 0:
                # No fuel and no capacity: nothing to show.
                note("no fuel type and no capacity")
                continue
            # Otherwise the unit has real capacity but Elexon does not declare a
            # fuel. That is missing data, not "other" -- 511 embedded units are
            # in this state, and they are exactly the ones whose region IS
            # published. Dropping them would discard the point of the map.
        operator = (row.get("leadPartyName") or "").strip()
        gsp_id = row.get("gspGroupId")

        units.append(Unit(
            bm_unit=bm_unit,
            name=(row.get("bmUnitName") or operator or bm_unit).strip(),
            fuel=fuel,
            connection=connection,
            capacity_mw=measured(capacity, BMU_SOURCE) if capacity and capacity > 0 else None,
            operator=measured(operator, BMU_SOURCE) if operator else None,
            gsp_group_id=measured(gsp_id, BMU_SOURCE) if gsp_id else None,
            gsp_group_name=measured(row["gspGroupName"], BMU_SOURCE)
                if row.get("gspGroupName") else None,
            interconnector_id=row.get("interconnectorId"),
        ))
    return units, skipped


def read_metered(path: Path) -> dict[str, float]:
    """Sum B1610 metered volumes per BM unit for the loaded period(s).

    Negative quantities are real: a unit can be a net consumer in a period (house
    load, auxiliary draw). They are kept rather than clipped, because clipping
    would quietly turn measured data into a cleaned-up estimate.
    """
    raw = json.loads(path.read_text())
    rows = raw if isinstance(raw, list) else raw.get("data", [])
    totals: dict[str, float] = {}
    for row in rows:
        unit = row.get("bmUnit")
        qty = _float(row.get("quantity"))
        if unit and qty is not None:
            totals[unit] = totals.get(unit, 0.0) + qty
    return totals


def read_regions(path: Path) -> list[Region]:
    """Parse the NESO DNO licence areas, reprojecting to WGS84 for the map."""
    from pyproj import Transformer

    data = json.loads(path.read_text())
    # NESO publishes EPSG:27700 (British National Grid); MapLibre needs WGS84.
    to_wgs84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)

    regions: list[Region] = []
    for feature in data["features"]:
        props = feature["properties"]
        regions.append(Region(
            code=props["Name"],
            area=props["Area"],
            dno=props["DNO"],
            dno_full=props["DNO_Full"],
            geometry=_reproject(feature["geometry"], to_wgs84),
        ))
    return regions


def _reproject(geometry: dict[str, Any], transformer) -> dict[str, Any]:
    def walk(coords: Any, depth: int) -> Any:
        if depth == 0:
            x, y = transformer.transform(coords[0], coords[1])
            return [round(x, 5), round(y, 5)]
        return [walk(c, depth - 1) for c in coords]

    depth = {"Polygon": 2, "MultiPolygon": 3, "LineString": 1, "Point": 0}[geometry["type"]]
    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"], depth)}


def recent_settlement_period() -> tuple[str, int]:
    """A settlement period recent enough to be interesting and old enough to be
    settled. B1610 is metered data, so it lags real time by days."""
    day = date.today() - timedelta(days=8)
    return day.isoformat(), 20  # period 20 = 09:30-10:00, a weekday-morning peak
