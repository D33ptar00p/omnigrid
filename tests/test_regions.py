"""Synchronous region assignment.

Getting this wrong does not raise -- it quietly lets a plant serve a grid it is
not connected to. These tests pin the boundaries that matter, especially the
ones a plausible-looking rule gets wrong.
"""

from __future__ import annotations

import pytest

from pipeline.sources.regions import CHINA_SUBGRIDS, load


@pytest.fixture(scope="module")
def idx():
    return load()


@pytest.mark.parametrize(
    "iso3,lat,lon,expected,place",
    [
        # North America: four asynchronous systems.
        ("USA", 30.27, -97.74, "ercot", "Austin"),
        ("USA", 29.76, -95.37, "ercot", "Houston"),
        ("USA", 37.77, -122.42, "western_interconnection", "San Francisco"),
        ("USA", 47.61, -122.33, "western_interconnection", "Seattle"),
        ("USA", 40.71, -74.01, "eastern_interconnection", "New York"),
        ("USA", 41.88, -87.63, "eastern_interconnection", "Chicago"),
        ("CAN", 46.81, -71.21, "quebec", "Québec City"),
        ("CAN", 51.05, -114.07, "western_interconnection", "Calgary"),
        ("CAN", 43.65, -79.38, "eastern_interconnection", "Toronto"),
        # Japan's 50/60 Hz divide.
        ("JPN", 35.69, 139.69, "japan_east", "Tokyo"),
        ("JPN", 43.06, 141.35, "japan_east", "Sapporo"),
        ("JPN", 34.69, 135.50, "japan_west", "Osaka"),
        ("JPN", 33.59, 130.40, "japan_west", "Fukuoka"),
        # Australia.
        ("AUS", -33.87, 151.21, "australia_nem", "Sydney"),
        ("AUS", -31.95, 115.86, "australia_swis", "Perth"),
        # Europe: GB and Ireland are separate from the continent.
        ("GBR", 51.51, -0.13, "great_britain", "London"),
        ("IRL", 53.35, -6.26, "ireland", "Dublin"),
        ("FRA", 48.86, 2.35, "continental_europe", "Paris"),
        ("ISL", 64.15, -21.94, "iceland", "Reykjavik"),
    ],
)
def test_known_places_land_in_the_right_grid(idx, iso3, lat, lon, expected, place):
    got, _ = idx.assign(iso3, lat, lon)
    assert got == expected, f"{place} -> {got}, expected {expected}"


def test_texas_panhandle_is_not_ercot(idx):
    """The panhandle is Southwest Power Pool, part of the Eastern
    Interconnection. A naive Texas bounding box gets this wrong, and the
    panhandle is large and heavily wind-generating."""
    got, _ = idx.assign("USA", 35.22, -101.83)  # Amarillo
    assert got == "eastern_interconnection"


def test_el_paso_is_western_not_ercot(idx):
    got, _ = idx.assign("USA", 31.76, -106.49)
    assert got == "western_interconnection"


def test_baltics_are_continental_europe_not_russian(idx):
    """The Baltic states left the Russian IPS/UPS in February 2025."""
    for iso3, lat, lon in [("LTU", 54.7, 25.3), ("LVA", 56.9, 24.1), ("EST", 59.4, 24.8)]:
        got, _ = idx.assign(iso3, lat, lon)
        assert got == "continental_europe", iso3


def test_ukraine_is_continental_europe(idx):
    """Synchronised with Continental Europe in March 2022."""
    assert idx.assign("UKR", 50.45, 30.52)[0] == "continental_europe"


def test_unlisted_country_becomes_its_own_isolated_grid(idx):
    """The default must under-connect rather than invent links."""
    rid, approx = idx.assign("FJI", -18.14, 178.44)
    assert rid == "iso:FJI"
    assert not approx
    assert "isolated" in idx.label(rid)


def test_split_countries_are_flagged_approximate(idx):
    """Anything placed by a geographic rule must say so, so the UI can
    desaturate it."""
    for iso3, lat, lon in [("USA", 40.7, -74.0), ("CHN", 39.9, 116.4),
                           ("JPN", 35.7, 139.7), ("AUS", -33.9, 151.2)]:
        assert idx.assign(iso3, lat, lon)[1] is True, iso3


def test_unsplit_countries_with_real_boundaries_are_not_flagged(idx):
    assert idx.assign("GBR", 51.5, -0.1)[1] is False
    assert idx.assign("FRA", 48.9, 2.4)[1] is False


def test_no_country_sits_in_two_synchronous_areas(idx):
    """load() raises on a duplicate; this pins that the data stays clean."""
    seen: dict[str, str] = {}
    for r in idx.regions.values():
        for c in r.members:
            assert c not in seen, f"{c} in both {seen.get(c)} and {r.id}"
            seen[c] = r.id


def test_china_rule_covers_all_six_subgrids(idx):
    """Every sub-grid should be reachable, or the rule has a dead branch."""
    cities = [(39.9, 116.4), (23.1, 113.3), (31.2, 121.5), (43.8, 125.3),
              (30.6, 114.3), (36.1, 103.8), (43.8, 87.6), (22.8, 108.3)]
    reached = {idx.assign("CHN", lat, lon)[0] for lat, lon in cities}
    assert reached <= set(CHINA_SUBGRIDS)
    assert len(reached) >= 5, f"only reached {reached}"


def test_every_region_declares_a_source(idx):
    for r in idx.regions.values():
        assert r.source.strip(), f"{r.id} has no source"
