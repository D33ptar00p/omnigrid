"""Build the Great Britain payload: measured generation and the real network.

Nothing in this module is modelled. Three things are joined, and the one place a
judgement is made -- matching an OSM plant to an Elexon BM Unit by name -- is
recorded as a record link with its basis, never presented as measurement.

What the map can honestly say about where power goes:

  * an embedded unit feeds a named distribution region, because Elexon publishes
    that link (gspGroupId) and NESO publishes the region's boundary;
  * a transmission-connected plant feeds the GB national grid, and therefore has
    no region. That is physics, not a gap in the data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.provenance import Cited, Kind, measured
from pipeline.schema import Fuel, UnknownFuel, is_non_generating, parse_fuel
from pipeline.sources import gb as gb_src

OSM_SOURCE = "osm_gb_power"

#: "1180 MW", "5.8 MW", "750 kW", "1.2 GW" -> MW
_POWER = re.compile(r"([0-9]*\.?[0-9]+)\s*([kMG]?)W", re.I)
_SCALE = {"": 1e-6, "k": 1e-3, "M": 1.0, "G": 1e3}


def parse_power_mw(text: str | None) -> float | None:
    """OSM records output as free text. Unparseable values return None rather
    than a guess -- a plant with an unreadable capacity tag is a plant with an
    unknown capacity."""
    if not text:
        return None
    total = 0.0
    found = False
    for value, prefix in _POWER.findall(text):
        try:
            total += float(value) * _SCALE[prefix if prefix in _SCALE else prefix.upper()]
        except (ValueError, KeyError):
            continue
        found = True
    return round(total, 3) if found else None


@dataclass(slots=True)
class Plant:
    """A power plant as mapped in OpenStreetMap: a surveyed object."""

    id: str
    name: str
    lat: float
    lon: float
    fuel: Cited[Fuel]
    capacity_mw: Cited[float] | None = None
    operator: Cited[str] | None = None
    #: Elexon BM Unit this was matched to, if any. A record link, not a fact
    #: published by either source.
    matched_unit: str | None = None
    match_basis: str | None = None
    #: Elexon units run by the same company. Weaker than a station match and
    #: labelled differently: it says who operates this plant also operates these
    #: units, not that they are the same plant.
    operator_units: list[dict[str, object]] = field(default_factory=list)
    #: DNO licence area this plant physically sits inside. A geographic fact --
    #: NOT a claim that the plant supplies that area.
    located_in: str | None = None
    located_in_code: str | None = None
    #: Photograph from Wikimedia Commons, with its own author and licence.
    image: dict[str, str | None] | None = None
    wikidata: str | None = None
    #: Offshore: outside every DNO area (those cover onshore distribution) but
    #: on the GB transmission system.
    offshore: bool = False
    #: Set when the plant is on another country's grid entirely.
    foreign_country: str | None = None
    other_system: str | None = None
    #: True for plants outside every GB DNO area: Northern Ireland, the Isle of
    #: Man and the Channel Islands are not on the GB distribution network.
    off_gb_network: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id, "name": self.name, "lat": self.lat, "lon": self.lon,
        }
        for key in ("fuel", "capacity_mw", "operator"):
            if (v := getattr(self, key)) is not None:
                out[key] = v.to_json()
        if self.matched_unit:
            out["matched_unit"] = self.matched_unit
            out["match_basis"] = self.match_basis
        if self.operator_units:
            out["operator_units"] = self.operator_units
        if self.located_in:
            out["located_in"] = self.located_in
            out["located_in_code"] = self.located_in_code
        out["off_gb_network"] = self.off_gb_network
        out["offshore"] = self.offshore
        if self.foreign_country:
            out["foreign_country"] = self.foreign_country
        if self.other_system:
            out["other_system"] = self.other_system
        if self.image:
            out["image"] = self.image
        if self.wikidata:
            out["wikidata"] = self.wikidata
        return out


@dataclass
class RegionSummary:
    """A DNO licence area with the embedded generation Elexon says feeds it."""

    code: str
    area: str
    dno: str
    dno_full: str
    geometry: dict[str, Any]
    embedded_units: int = 0
    embedded_capacity_mw: float = 0.0
    fuel_mix_mw: dict[str, float] = field(default_factory=dict)
    metered_mwh: float = 0.0
    fuel_undeclared_mw: float = 0.0

    def to_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {
                "code": self.code, "area": self.area,
                "dno": self.dno, "dno_full": self.dno_full,
                "embedded_units": self.embedded_units,
                "embedded_capacity_mw": round(self.embedded_capacity_mw, 1),
                "fuel_mix_mw": {k: round(v, 1) for k, v in self.fuel_mix_mw.items()},
                "fuel_undeclared_mw": round(self.fuel_undeclared_mw, 1),
                "metered_mwh": round(self.metered_mwh, 2),
                "dominant_fuel": max(self.fuel_mix_mw, key=self.fuel_mix_mw.get)
                if self.fuel_mix_mw else None,
            },
        }


def read_osm_plants(path: Path) -> tuple[list[Plant], dict[str, int]]:
    """Parse an Overpass dump of power=plant in GB."""
    data = json.loads(path.read_text())
    plants: list[Plant] = []
    skipped: dict[str, int] = {}

    def note(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for el in data.get("elements", []):
        tags = el.get("tags", {})
        source = tags.get("plant:source") or tags.get("generator:source")
        if not source:
            note("no plant:source")
            continue
        if is_non_generating(source):
            note(f"storage ({source})")
            continue
        try:
            fuel = parse_fuel(source)
        except UnknownFuel:
            note(f"unmapped source: {source}")
            continue

        centre = el.get("center") or el
        lat, lon = centre.get("lat"), centre.get("lon")
        if lat is None or lon is None:
            note("no location")
            continue

        capacity = parse_power_mw(tags.get("plant:output:electricity"))
        operator = (tags.get("operator") or "").strip()
        qid = (tags.get("wikidata") or "").strip()

        plants.append(Plant(
            wikidata=qid if qid.startswith("Q") else None,
            id=f"osm:{el['type']}/{el['id']}",
            name=(tags.get("name") or "").strip() or f"Unnamed {source} plant",
            lat=round(float(lat), 6), lon=round(float(lon), 6),
            fuel=measured(fuel, OSM_SOURCE),
            capacity_mw=measured(capacity, OSM_SOURCE) if capacity else None,
            operator=measured(operator, OSM_SOURCE) if operator else None,
        ))
    return plants, skipped


_NOISE = re.compile(
    r"\b(power\s*station|power\s*plant|wind\s*farm|windfarm|solar\s*farm|"
    r"generating\s*station|energy\s*(from\s*waste|centre|park)|"
    r"offshore|onshore|limited|ltd|plc|the)\b", re.I)


def normalise_name(name: str) -> str:
    """Reduce a plant name to something comparable across two sources."""
    s = _NOISE.sub(" ", name.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_units(plants: list[Plant], units: list[gb_src.Unit]) -> int:
    """Link OSM plants to Elexon BM Units by name.

    This is the one inference in the GB build, and it is deliberately
    conservative: an exact match on the normalised name, and only where that
    name is unique on both sides. Fuzzy matching would link more plants and
    would silently link some of them wrongly. Every link records its basis so
    the UI can show it as a link rather than a measurement.
    """
    by_name: dict[str, list[gb_src.Unit]] = {}
    for u in units:
        if not u.is_generation:
            continue
        key = normalise_name(u.name)
        if key:
            by_name.setdefault(key, []).append(u)

    plants_by_name: dict[str, list[Plant]] = {}
    for p in plants:
        key = normalise_name(p.name)
        if key:
            plants_by_name.setdefault(key, []).append(p)

    matched = 0
    for key, candidates in plants_by_name.items():
        units_here = by_name.get(key)
        # Unique on both sides, or we cannot tell which is which.
        if not units_here or len(units_here) != 1 or len(candidates) != 1:
            continue
        candidates[0].matched_unit = units_here[0].bm_unit
        candidates[0].match_basis = (
            f"Names match exactly after normalisation "
            f"(OSM {candidates[0].name!r} ↔ Elexon {units_here[0].name!r}), and "
            "the name is unique in both sources. This link is our judgement, "
            "not an identifier published by either source."
        )
        matched += 1
    return matched


def locate_plants(plants: list[Plant], regions: list[gb_src.Region],
                  boundaries: Path | None = None) -> tuple[int, int]:
    """Place each plant: onshore in a DNO area, offshore, or on another system.

    Three outcomes, and the distinction matters because the naive version got it
    wrong twice. "Located in South Wales" is geography, not power flow -- it says
    where the station is, not who it supplies.

      * inside a DNO licence area -> onshore GB
      * on land but outside every DNO area -> Northern Ireland (all-island Irish
        system), the Isle of Man, or the Channel Islands: real stations, but not
        on the GB grid
      * not on land at all -> offshore. Offshore wind farms sit outside every DNO
        area because those cover onshore distribution, yet they are firmly on the
        GB transmission system. Treating "outside a DNO area" as "not GB" would
        exile Hornsea and Dogger Bank.

    Returns (off_network, offshore).
    """
    from shapely.geometry import shape
    from shapely.prepared import prep
    from shapely import Point, STRtree

    shapes = [shape(r.geometry) for r in regions]
    tree = STRtree(shapes)
    prepared = [prep(g) for g in shapes]

    land = _land_polygons(boundaries) if boundaries else {}
    land_shapes = list(land.values())
    land_codes = list(land)
    land_tree = STRtree(land_shapes) if land_shapes else None

    off = offshore = 0
    for p in plants:
        point = Point(p.lon, p.lat)
        hit = None
        for idx in tree.query(point):
            if prepared[idx].contains(point):
                hit = idx
                break
        if hit is not None:
            p.located_in = regions[hit].area
            p.located_in_code = regions[hit].code
            continue

        country = _country_at(point, land_tree, land_shapes, land_codes)
        if country is None:
            # At sea. Attribute it to the nearest coastline, which for the North
            # Sea farms is the right answer and is at least a stated rule.
            nearest = _nearest_country(point, land_tree, land_shapes, land_codes)
            if nearest == "GBR":
                p.offshore = True
                p.located_in = "Offshore"
                offshore += 1
            else:
                p.off_gb_network = True
                p.foreign_country = nearest
                off += 1
        elif country == "GBR":
            # GBR land outside every DNO area is Northern Ireland.
            p.off_gb_network = True
            p.other_system = "Northern Ireland (all-island Irish system)"
            off += 1
        else:
            p.off_gb_network = True
            p.foreign_country = country
            off += 1
    return off, offshore


def _land_polygons(boundaries: Path) -> dict[str, object]:
    """Country land polygons from Natural Earth, keyed by ISO3.

    Read through DuckDB's spatial extension, which is already a dependency and
    handles the zipped shapefile without a GeoPandas stack.
    """
    import duckdb
    from shapely import wkb
    from shapely.ops import unary_union

    path = str(boundaries)
    if boundaries.suffix == ".zip":
        path = f"/vsizip/{boundaries}/{boundaries.stem}.shp"

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute(
        "SELECT ADM0_A3 AS iso3, ST_AsWKB(geom) AS wkb FROM st_read(?)", [path]
    ).fetchall()
    con.close()

    by_country: dict[str, list] = {}
    for iso3, blob in rows:
        if not iso3 or blob is None:
            continue
        try:
            by_country.setdefault(iso3, []).append(wkb.loads(bytes(blob)))
        except Exception:
            continue
    return {k: (v[0] if len(v) == 1 else unary_union(v)) for k, v in by_country.items()}


def _country_at(point, tree, shapes, codes) -> str | None:
    """ISO3 of the country whose land contains this point, or None if at sea."""
    if tree is None:
        return None
    for idx in tree.query(point):
        if shapes[int(idx)].contains(point):
            return codes[int(idx)]
    return None


def _nearest_country(point, tree, shapes, codes, max_degrees: float = 4.0) -> str | None:
    """ISO3 of the nearest coastline.

    Offshore wind farms have no country polygon of their own, so the nearest
    coast is the rule used to attribute them. It is crude but stated, and for
    the North Sea and Irish Sea farms it lands correctly.
    """
    if tree is None:
        return None
    best_code, best_dist = None, float("inf")
    for idx in tree.query(point.buffer(max_degrees)):
        d = shapes[int(idx)].distance(point)
        if d < best_dist:
            best_dist, best_code = d, codes[int(idx)]
    return best_code


#: Company-name noise. "Drax Power Ltd" and "Drax Group PLC" are the same firm;
#: the distinctive part is the first token that is not one of these.
_COMPANY_NOISE = {
    "power", "energy", "energies", "group", "ltd", "limited", "plc", "llp", "uk",
    "gb", "holdings", "generation", "renewables", "solutions", "services", "and",
    "the", "company", "corporation", "inc", "gmbh", "bv", "as", "a", "s",
    "trading", "markets", "supply", "international", "operations", "investments",
}


def company_key(name: str) -> str | None:
    """The distinctive leading token of a company name, or None if there isn't one.

    Deliberately crude and deliberately labelled: this identifies a *firm*, not a
    station. "Drax Power Ltd" and "Drax Group PLC" both key to "drax", which is
    right; "National Grid" keys to "national", which is why the result is shown
    as "same operator" and never as a station match.
    """
    for token in re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split():
        if token not in _COMPANY_NOISE and len(token) > 2:
            return token
    return None


def link_by_operator(plants: list[Plant], units: list[gb_src.Unit],
                     metered: dict[str, float]) -> int:
    """Attach Elexon units run by the same company as the plant's OSM operator.

    Elexon names most large stations only by BM Unit code -- Drax is T_DRAXX-1
    through -6 -- so a station-level name match is impossible for exactly the
    plants people most want to look at. Linking at the company level is weaker
    but true, and the UI says which kind of link it is.
    """
    by_company: dict[str, list[gb_src.Unit]] = {}
    for u in units:
        if not u.is_generation or not u.operator or not u.capacity_mw:
            continue
        if key := company_key(u.operator.value):
            by_company.setdefault(key, []).append(u)

    linked = 0
    for p in plants:
        if not p.operator:
            continue
        key = company_key(p.operator.value)
        if not key or key not in by_company:
            continue
        units_here = sorted(by_company[key],
                            key=lambda u: -(u.capacity_mw.value if u.capacity_mw else 0))
        p.operator_units = [
            {"bm_unit": u.bm_unit,
             "capacity_mw": round(u.capacity_mw.value, 1) if u.capacity_mw else None,
             "fuel": u.fuel.value.value if u.fuel else None,
             "operator": u.operator.value if u.operator else None,
             "metered_mwh": round(metered[u.bm_unit], 2)
             if u.bm_unit in metered else None}
            for u in units_here[:24]
        ]
        linked += 1
    return linked


def summarise_regions(
    regions: list[gb_src.Region],
    units: list[gb_src.Unit],
    metered: dict[str, float],
) -> list[RegionSummary]:
    """Attach each region's published embedded generation.

    Entirely from published fields: Elexon states which GSP group an embedded
    unit sits in, and NESO states where that group is.
    """
    summaries = {
        r.code: RegionSummary(r.code, r.area, r.dno, r.dno_full, r.geometry)
        for r in regions
    }
    for u in units:
        if u.connection is not gb_src.Connection.EMBEDDED or not u.gsp_group_id:
            continue
        s = summaries.get(u.gsp_group_id.value)
        if s is None:
            continue
        s.embedded_units += 1
        mw = u.capacity_mw.value if u.capacity_mw else 0.0
        s.embedded_capacity_mw += mw
        if u.fuel is not None:
            key = u.fuel.value.value
            s.fuel_mix_mw[key] = s.fuel_mix_mw.get(key, 0.0) + mw
        else:
            s.fuel_undeclared_mw += mw
        s.metered_mwh += metered.get(u.bm_unit, 0.0)
    return list(summaries.values())


# --- build ------------------------------------------------------------------

DIST = Path(__file__).resolve().parent.parent / "data" / "dist" / "gb"


@dataclass
class GBReport:
    plants: int = 0
    plants_capacity_gw: float = 0.0
    units_transmission: int = 0
    units_embedded: int = 0
    interconnectors: int = 0
    matched: int = 0
    off_network: int = 0
    with_image: int = 0
    lines: int = 0
    substation_joins: int = 0
    plants_wired: int = 0
    operator_linked: int = 0
    offshore: int = 0
    gb_plants: int = 0
    offshore_capacity_gw: float = 0.0
    metered_gw: float = 0.0
    settlement: str = ""
    regions: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def build(raw: Path, dist: Path = DIST, *, settlement: str = "") -> GBReport:
    """Assemble every GB output from already-fetched raw files."""
    from pipeline.sources.gb import (
        Connection, read_metered, read_regions, read_units,
    )

    dist.mkdir(parents=True, exist_ok=True)
    report = GBReport(settlement=settlement)

    from pipeline.sources.wikidata import load_cache

    units, unit_skipped = read_units(raw / "elexon_bmu" / "bmunits.json")
    metered = read_metered(raw / "elexon_b1610" / "b1610.json")
    regions = read_regions(raw / "neso_dno_areas" / "dno_areas.geojson")
    plants, plant_skipped = read_osm_plants(raw / "osm_gb_power" / "plants.json")

    images = load_cache(raw / "wikidata" / "images.json")
    for p in plants:
        if p.wikidata and (img := images.get(p.wikidata)):
            p.image = img.to_json()
    report.with_image = sum(1 for p in plants if p.image)

    report.matched = match_units(plants, units)
    report.operator_linked = link_by_operator(plants, units, metered)
    report.off_network, report.offshore = locate_plants(
        plants, regions, raw / "natural_earth" / "ne_50m_admin_0_countries.zip")
    summaries = summarise_regions(regions, units, metered)

    # Metered output onto matched plants, so the map can show what a station is
    # actually producing rather than only what it could.
    by_unit = {u.bm_unit: u for u in units}
    for p in plants:
        if p.matched_unit and (mwh := metered.get(p.matched_unit)) is not None:
            unit = by_unit.get(p.matched_unit)
            if unit is not None:
                unit.metered_mwh = measured(round(mwh, 2), gb_src.B1610_SOURCE)

    (dist / "plants.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p.lon, p.lat]},
            "properties": {
                **p.to_json(),
                "_operator": p.operator.value if p.operator else "",
                "_fuel": p.fuel.value.value,
                "_mw": p.capacity_mw.value if p.capacity_mw else 0,
            },
        } for p in plants],
    }, separators=(",", ":")))

    (dist / "regions.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [s.to_feature() for s in summaries],
    }, separators=(",", ":")))

    (dist / "units.json").write_text(json.dumps({
        "settlement": settlement,
        "units": [
            {**u.to_json(),
             "metered_mwh": u.metered_mwh.to_json() if u.metered_mwh else None}
            for u in units if u.is_generation and (u.capacity_mw or u.fuel)
        ],
        "interconnectors": sorted({
            u.interconnector_id for u in units
            if u.connection is Connection.INTERCONNECTOR and u.interconnector_id
        }),
    }, separators=(",", ":")))

    # GB totals exclude plants on other grids, and must be known before
    # anything reports against them.
    gb_plants = [p for p in plants if not p.off_gb_network]
    report.gb_plants = len(gb_plants)
    report.plants_capacity_gw = sum(
        p.capacity_mw.value for p in gb_plants if p.capacity_mw) / 1000
    report.offshore_capacity_gw = sum(
        p.capacity_mw.value for p in plants if p.offshore and p.capacity_mw) / 1000

    # --- the physical grid --------------------------------------------------
    lines_path = raw / "osm_gb_power" / "lines.json"
    if lines_path.exists():
        from pipeline import grid as grid_mod

        graph = grid_mod.build_graph(
            lines_path, substations=raw / "osm_gb_power" / "substations.json")
        conns = grid_mod.connections_bulk(
            graph, [(p.lon, p.lat) for p in plants], radius_km=2.0)

        (dist / "lines.geojson").write_text(
            json.dumps(grid_mod.to_geojson(graph), separators=(",", ":")))
        (dist / "adjacency.json").write_text(
            json.dumps(grid_mod.adjacency_json(graph), separators=(",", ":")))
        (dist / "connections.json").write_text(json.dumps(
            {plants[i].id: c for i, c in enumerate(conns) if c},
            separators=(",", ":")))

        report.lines = len(graph.lines)
        report.substation_joins = graph.substation_joins
        report.plants_wired = sum(1 for c in conns if c)
        report.notes.append(
            f"{report.plants_wired:,} of {report.gb_plants:,} GB plants sit within 2 km of a "
            "mapped transmission line. The rest are embedded in distribution "
            "networks that OpenStreetMap maps less completely, or are too small to "
            "have a traced connection."
        )
        report.notes.append(
            "Tracing follows surveyed wires, which is a real question with a real "
            "answer. It is not a claim about where the electricity goes: the GB "
            "transmission network is one connected graph, so a full trace from "
            "almost any station reaches most of the country."
        )

    report.plants = len(plants)
    report.units_transmission = sum(
        1 for u in units if u.connection is Connection.TRANSMISSION)
    report.units_embedded = sum(
        1 for u in units if u.connection is Connection.EMBEDDED)
    report.interconnectors = len({
        u.interconnector_id for u in units
        if u.connection is Connection.INTERCONNECTOR and u.interconnector_id})
    report.metered_gw = sum(v for v in metered.values() if v > 0) * 2 / 1000
    report.regions = len(summaries)
    report.skipped = {**unit_skipped, **plant_skipped}
    report.notes.append(
        f"{report.matched} of {report.gb_plants:,} GB plants matched to an Elexon BM "
        "Unit by exact normalised name. Unmatched plants still show their surveyed "
        "location, fuel and capacity; they simply have no metered output attached."
    )
    report.notes.append(
        f"{report.units_transmission} transmission-connected units have no "
        "distribution region, because they feed the GB national grid. That is "
        "physics, not missing data."
    )
    if report.offshore:
        report.notes.append(
            f"{report.offshore} offshore plants ({report.offshore_capacity_gw:,.1f} GW) "
            "sit outside every DNO licence area, because those cover onshore "
            "distribution. They are on the GB transmission system and are counted "
            "as GB. An earlier query missed them entirely: it used the UK land "
            "boundary, so every wind farm beyond territorial waters fell outside it."
        )
    if report.off_network:
        report.notes.append(
            f"{report.off_network} plants in the map's bounds are on another grid "
            "— Northern Ireland's all-island Irish system, or Ireland, France, "
            "Belgium and Norway. They are shown dimmed and excluded from GB totals."
        )
    undeclared = sum(s.fuel_undeclared_mw for s in summaries)
    declared = sum(sum(s.fuel_mix_mw.values()) for s in summaries)
    if undeclared > declared:
        report.notes.append(
            f"Elexon declares no fuel type for {undeclared/1000:,.1f} GW of the "
            f"{(undeclared+declared)/1000:,.1f} GW of embedded capacity. Regions are "
            "therefore shaded by capacity, not by fuel: colouring by the declared "
            "minority would present a third of the data as if it were all of it."
        )
    return report
