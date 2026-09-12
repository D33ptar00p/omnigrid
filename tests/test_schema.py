"""The fuel taxonomy must be total: nothing may fall through to OTHER silently.

A silent fallthrough would be invisible in the UI and would poison the
capacity-factor calibration, since OTHER has no defensible capacity factor.
"""

from __future__ import annotations

import pytest

from pipeline.schema import (
    FUEL_ALIASES, Fuel, Status, UnknownFuel, is_non_generating, parse_fuel, parse_status,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Coal", Fuel.COAL), ("lignite", Fuel.COAL), ("Petcoke", Fuel.COAL),
        ("Gas", Fuel.GAS), ("Cogeneration", Fuel.GAS), ("LNG", Fuel.GAS),
        ("Oil", Fuel.OIL), ("Nuclear", Fuel.NUCLEAR),
        ("Hydro", Fuel.HYDRO), ("Wave and Tidal", Fuel.HYDRO),
        ("Wind", Fuel.WIND), ("Solar", Fuel.SOLAR), ("Geothermal", Fuel.GEOTHERMAL),
        ("Biomass", Fuel.BIOENERGY), ("Waste", Fuel.BIOENERGY),
    ],
)
def test_known_fuels_map(raw, expected):
    assert parse_fuel(raw) is expected


def test_unmapped_fuel_raises_rather_than_becoming_other():
    with pytest.raises(UnknownFuel, match="unmapped fuel"):
        parse_fuel("Plasma Fusion Reactor")


def test_multi_fuel_takes_the_primary_source():
    """OpenStreetMap writes multi-fuel plants as "oil;gas". The first value is
    the primary source by convention; inventing a blend would be worse."""
    assert parse_fuel("oil;gas") is Fuel.OIL
    assert parse_fuel("biomass;waste") is Fuel.BIOENERGY
    assert parse_fuel("wind;solar") is Fuel.WIND


def test_liquid_air_is_storage_not_generation():
    from pipeline.schema import is_non_generating

    assert is_non_generating("liquid_air")


def test_empty_fuel_raises():
    for bad in (None, "", "   "):
        with pytest.raises(UnknownFuel):
            parse_fuel(bad)


def test_storage_is_rejected_not_classified():
    """Storage is negative-then-positive energy; counting it as generation inflates GW."""
    for s in ("Storage", "battery", "Pumped Storage"):
        assert is_non_generating(s)
        with pytest.raises(UnknownFuel, match="storage, not generation"):
            parse_fuel(s)


def test_parsing_is_case_and_whitespace_insensitive():
    assert parse_fuel("  CoAl  ") is Fuel.COAL


def test_only_explicit_values_reach_other():
    """OTHER must be reachable only from values that genuinely mean it.

    The set is pinned so that adding a mapping to OTHER is a deliberate act.
    `waste_heat` and `minewater` are real OpenStreetMap sources in GB that fit
    none of the nine named categories; they belong in OTHER, unlike a fuel we
    simply failed to map, which must raise.
    """
    reaching = {k for k, v in FUEL_ALIASES.items() if v is Fuel.OTHER}
    assert reaching == {"other", "unknown", "waste_heat", "minewater"}


def test_fossil_and_renewable_partition_is_sane():
    fossil = {f for f in Fuel if f.is_fossil}
    renew = {f for f in Fuel if f.is_renewable}
    assert fossil == {Fuel.COAL, Fuel.OIL, Fuel.GAS}
    assert not fossil & renew
    assert (fossil | renew) == set(Fuel) - {Fuel.NUCLEAR, Fuel.OTHER}


def test_only_operating_counts_as_supply():
    """Including announced units fabricates supply; leaving retired ones in
    fabricates it differently."""
    assert Status.OPERATING.counts_as_supply
    for s in Status:
        if s is not Status.OPERATING:
            assert not s.counts_as_supply


def test_status_aliases():
    assert parse_status("Under construction") is Status.CONSTRUCTION
    assert parse_status("pre-construction") is Status.ANNOUNCED
    assert parse_status("Decommissioned") is Status.RETIRED
    assert parse_status(None) is Status.OPERATING
