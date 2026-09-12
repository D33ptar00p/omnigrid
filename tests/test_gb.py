"""Great Britain: the measured build.

The distinctions these tests pin are the ones that make the GB view honest --
what is published, what is geography, and what is our own judgement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.gb import normalise_name, parse_power_mw, read_osm_plants
from pipeline.sources.gb import (
    Connection, UnknownFuelType, read_metered, read_units,
)

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
pytestmark = pytest.mark.skipif(
    not (RAW / "elexon_bmu" / "bmunits.json").exists(),
    reason="GB raw inputs not fetched",
)


@pytest.fixture(scope="module")
def units():
    return read_units(RAW / "elexon_bmu" / "bmunits.json")[0]


# ---- power parsing ---------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("1180 MW", 1180.0), ("5.8 MW", 5.8), ("750 kW", 0.75), ("1.2 GW", 1200.0),
])
def test_parses_osm_power_tags(text, expected):
    assert parse_power_mw(text) == pytest.approx(expected)


def test_unreadable_power_returns_none_rather_than_a_guess():
    """A plant with an unreadable capacity tag has an unknown capacity, not zero."""
    assert parse_power_mw("lots") is None
    assert parse_power_mw(None) is None
    assert parse_power_mw("") is None


# ---- the connection distinction -------------------------------------------


def test_only_embedded_units_carry_a_published_region(units):
    """The crux of the view: Elexon publishes a region for embedded units and
    not for transmission-connected ones, because the latter feed all of GB."""
    for u in units:
        if u.connection is Connection.EMBEDDED:
            assert u.gsp_group_id is not None, u.bm_unit
        elif u.connection is Connection.TRANSMISSION:
            assert u.gsp_group_id is None, u.bm_unit


def test_connection_kinds_describe_themselves(units):
    assert Connection.EMBEDDED.has_published_region
    assert not Connection.TRANSMISSION.has_published_region
    assert not Connection.INTERCONNECTOR.has_published_region
    assert "national grid" in Connection.TRANSMISSION.description.lower()


def test_interconnectors_are_grouped_by_physical_link(units):
    """1,300 accounting BM Units represent ten physical links. Counting the
    units instead claimed ~700 GW of interconnection for a country with ~10."""
    from pipeline.sources.gb import GBData

    links = GBData(units=units).interconnectors
    assert 8 <= len(links) <= 14, f"expected roughly ten links, got {len(links)}"
    assert "BRITNED" in links
    assert sum(len(v) for v in links.values()) > 100


def test_pumped_storage_is_excluded_from_generation():
    """Pumped storage moves energy in time; counting it as generation
    double-counts the electricity used to fill it."""
    _, skipped = read_units(RAW / "elexon_bmu" / "bmunits.json")
    assert skipped.get("pumped storage (not generation)", 0) > 0


def test_units_without_a_declared_fuel_are_kept_not_coerced(units):
    """511 embedded units have real capacity but no declared fuel -- and they
    are exactly the units whose region is published. Dropping them, or calling
    them "other", would discard the point of the view."""
    undeclared = [u for u in units
                  if u.connection is Connection.EMBEDDED and not u.fuel_declared]
    assert undeclared, "expected embedded units with no declared fuel"
    assert all(u.fuel is None for u in undeclared)
    assert all(u.capacity_mw is not None for u in undeclared)


def test_unmapped_elexon_fuel_type_raises(tmp_path):
    bad = tmp_path / "bmu.json"
    bad.write_text(json.dumps([{
        "elexonBmUnit": "T_TEST-1", "bmUnitName": "Test",
        "fuelType": "ANTIMATTER", "bmUnitType": "T", "generationCapacity": "100",
    }]))
    with pytest.raises(UnknownFuelType, match="ANTIMATTER"):
        read_units(bad)


# ---- metered output --------------------------------------------------------


def test_metered_volumes_keep_their_sign():
    """A unit can be a net consumer in a settlement period. Clipping would turn
    measured data into a tidied-up estimate."""
    metered = read_metered(RAW / "elexon_b1610" / "b1610.json")
    assert metered
    assert any(v < 0 for v in metered.values())


def test_metered_total_is_a_plausible_gb_load():
    metered = read_metered(RAW / "elexon_b1610" / "b1610.json")
    gw = sum(v for v in metered.values() if v > 0) * 2 / 1000
    assert 10 < gw < 70, f"{gw:.1f} GW is not a plausible GB half-hour"


# ---- OSM plants ------------------------------------------------------------


def test_osm_plants_have_real_coordinates_inside_gb():
    plants, _ = read_osm_plants(RAW / "osm_gb_power" / "plants.json")
    assert len(plants) > 2000
    for p in plants:
        assert 49 < p.lat < 61.5, f"{p.name} at {p.lat}"
        assert -9 < p.lon < 2.5, f"{p.name} at {p.lon}"


def test_batteries_are_not_counted_as_generation():
    _, skipped = read_osm_plants(RAW / "osm_gb_power" / "plants.json")
    assert skipped.get("storage (battery)", 0) > 0


def test_no_osm_source_falls_through_unmapped():
    """An unmapped fuel is a gap to close, not a plant that burns 'other'."""
    _, skipped = read_osm_plants(RAW / "osm_gb_power" / "plants.json")
    unmapped = {k: v for k, v in skipped.items() if k.startswith("unmapped")}
    assert not unmapped, f"unmapped OSM sources: {unmapped}"


# ---- the one judgement in the build ----------------------------------------


def test_name_normalisation_strips_boilerplate():
    assert normalise_name("Seabank Power Station") == "seabank"
    assert normalise_name("Drax Power Ltd") == "drax power"
    assert normalise_name("Whitelee Wind Farm") == "whitelee"


def test_matches_are_conservative_and_record_their_basis():
    """The OSM-to-Elexon link is our judgement, not a published identifier, so
    it must be rare, exact, and self-describing."""
    from pipeline.gb import match_units

    plants, _ = read_osm_plants(RAW / "osm_gb_power" / "plants.json")
    units, _ = read_units(RAW / "elexon_bmu" / "bmunits.json")
    matched = match_units(plants, units)

    assert 0 < matched < len(plants) * 0.2, "matching should stay conservative"
    for p in plants:
        if p.matched_unit:
            assert p.match_basis and "judgement" in p.match_basis
