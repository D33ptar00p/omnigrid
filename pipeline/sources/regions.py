"""Assign every asset and demand cell to a synchronous grid region.

The allocation model runs independently per region, so this module is what
enforces "electrons do not cross a synchronous boundary". Getting it wrong does
not raise -- it quietly lets a plant serve a grid it is not connected to -- which
is why the splits below are explicit, sourced and marked approximate.

Seven countries span more than one synchronous area. Real boundaries for those
are not open data (NERC and WECC publish maps, not machine-readable geometry),
so each uses a documented geographic rule. Assets placed by a rule are tagged
`approximate`, which feeds the UI's confidence layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

REGIONS_PATH = Path(__file__).with_name("regions.yaml")
SOURCE_ID = "omnigrid_regions"


@dataclass(frozen=True, slots=True)
class Region:
    id: str
    name: str
    source: str
    members: frozenset[str]
    split: str | None = None
    approximate: bool = False
    notes: str | None = None


# --- geographic split rules -------------------------------------------------
#
# Each returns a region id. Coordinates are (lat, lon). These are deliberately
# simple: a wrong-but-documented rule beats a plausible-looking polygon nobody
# can check.

def _north_america(lat: float, lon: float) -> str:
    """NERC interconnections. Boundaries are utility-by-utility in reality; the
    WECC edge runs roughly down the eastern Rockies near -104 longitude."""
    # Québec: asynchronous, HVDC ties only.
    if 45.0 <= lat <= 62.5 and -79.5 <= lon <= -57.0:
        return "quebec"
    # ERCOT: most of Texas, but not all of it. Three real exclusions:
    #   - the panhandle (north of ~34.5, west of ~-100) is Southwest Power Pool,
    #     part of the Eastern Interconnection;
    #   - the El Paso area in the far west is Western Interconnection;
    #   - a strip of far east Texas is also Eastern.
    # The panhandle exclusion matters: it is large and heavily wind-generating.
    if 25.8 <= lat <= 36.5 and -103.0 <= lon <= -93.5:
        in_panhandle = lat > 34.5 and lon < -100.0
        if not in_panhandle:
            return "ercot"
    if lon < -104.0:
        return "western_interconnection"
    return "eastern_interconnection"


def _japan(lat: float, lon: float) -> str:
    """The 50/60 Hz divide runs through Honshu near the Fuji/Itoigawa line.
    Only frequency converters cross it, so the two halves are separate systems."""
    del lat
    return "japan_east" if lon >= 137.8 else "japan_west"


def _australia(lat: float, lon: float) -> str:
    """SWIS covers the WA southwest; the NEM covers the eastern seaboard. The
    Northern Territory and remote WA are neither, but are folded into the
    nearer of the two rather than given a region with almost no demand."""
    del lat
    return "australia_swis" if lon < 129.0 else "australia_nem"


def _china(lat: float, lon: float) -> str:
    """Six regional grids joined by HVDC, so asynchronous. This is the weakest
    curation in the table -- province membership is what actually determines the
    grid, and this approximates it with geography."""
    if lat >= 41.0 and lon >= 118.0:
        return "china_northeast"
    if lon < 100.0 or (lat >= 35.0 and lon < 110.0):
        return "china_northwest"
    if lat >= 36.0:
        return "china_north"
    if lat < 27.0 and lon < 117.0:
        return "china_southern"
    if lon >= 115.0:
        return "china_east"
    return "china_central"


SPLIT_RULES: dict[str, Callable[[float, float], str]] = {
    "na_parent": _north_america,
    "au_parent": _australia,
    "japan_east": _japan,
    "china": _china,
}

#: China's six sub-grids are produced by the rule rather than listed in YAML,
#: since none of them has its own country membership.
CHINA_SUBGRIDS = {
    "china_north": "North China Grid",
    "china_northeast": "Northeast China Grid",
    "china_northwest": "Northwest China Grid",
    "china_central": "Central China Grid",
    "china_east": "East China Grid",
    "china_southern": "China Southern Power Grid",
}


@dataclass
class RegionIndex:
    regions: dict[str, Region]
    _by_country: dict[str, Region]

    def __getitem__(self, region_id: str) -> Region | None:
        return self.regions.get(region_id)

    def assign(self, country: str, lat: float, lon: float) -> tuple[str, bool]:
        """Return (region_id, approximate).

        A country with no entry gets a region of its own -- an isolated national
        grid. That default under-connects rather than inventing links, which is
        the safer error: it shrinks sheds instead of spreading them across a
        boundary that does not exist.
        """
        region = self._by_country.get(country)
        if region is None:
            return f"iso:{country}", False
        if region.split and (rule := SPLIT_RULES.get(region.split)):
            return rule(lat, lon), True
        return region.id, region.approximate

    def label(self, region_id: str) -> str:
        if region_id.startswith("iso:"):
            return f"{region_id[4:]} (isolated)"
        if region_id in CHINA_SUBGRIDS:
            return CHINA_SUBGRIDS[region_id]
        r = self.regions.get(region_id)
        return r.name if r else region_id


@lru_cache(maxsize=1)
def load(path: Path = REGIONS_PATH) -> RegionIndex:
    raw = yaml.safe_load(path.read_text())
    if raw.get("schema_version") != 1:
        raise ValueError(f"unsupported regions schema_version {raw.get('schema_version')!r}")

    regions: dict[str, Region] = {}
    by_country: dict[str, Region] = {}
    for rid, r in raw["regions"].items():
        region = Region(
            id=rid,
            name=r["name"],
            source=r["source"],
            members=frozenset(r.get("members", ())),
            split=r.get("split"),
            approximate=bool(r.get("approximate", False)),
            notes=r.get("notes"),
        )
        regions[rid] = region
        for c in region.members:
            if c in by_country:
                raise ValueError(
                    f"country {c} assigned to both {by_country[c].id} and {rid}; "
                    "a country cannot sit in two synchronous areas"
                )
            by_country[c] = region

    for rid, name in CHINA_SUBGRIDS.items():
        regions[rid] = Region(rid, name, regions["china_grids"].source,
                              frozenset(), None, True, None)
    return RegionIndex(regions, by_country)


if __name__ == "__main__":
    idx = load()
    print(f"{len(idx.regions)} regions, {len(idx._by_country)} countries mapped\n")
    checks = [
        ("USA", 31.0, -97.5, "Austin TX"), ("USA", 37.8, -122.4, "San Francisco"),
        ("USA", 40.7, -74.0, "New York"), ("USA", 35.2, -101.8, "Amarillo TX"),
        ("CAN", 46.8, -71.2, "Québec City"), ("CAN", 51.0, -114.1, "Calgary"),
        ("JPN", 35.7, 139.7, "Tokyo"), ("JPN", 34.7, 135.5, "Osaka"),
        ("CHN", 39.9, 116.4, "Beijing"), ("CHN", 23.1, 113.3, "Guangzhou"),
        ("CHN", 31.2, 121.5, "Shanghai"), ("CHN", 43.8, 125.3, "Changchun"),
        ("AUS", -33.9, 151.2, "Sydney"), ("AUS", -31.9, 115.9, "Perth"),
        ("GBR", 51.5, -0.1, "London"), ("FRA", 48.9, 2.4, "Paris"),
        ("LTU", 54.7, 25.3, "Vilnius"), ("FJI", -18.1, 178.4, "Suva (unlisted)"),
    ]
    for c, lat, lon, place in checks:
        rid, approx = idx.assign(c, lat, lon)
        print(f"  {place:22} {c}  ->  {idx.label(rid):32} {'~approx' if approx else ''}")
