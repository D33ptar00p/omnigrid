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
    """OTHER must be reachable only from source values that genuinely mean it."""
    reaching = {k for k, v in FUEL_ALIASES.items() if v is Fuel.OTHER}
    assert reaching == {"other", "unknown"}


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
