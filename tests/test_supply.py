"""Capacity-factor calibration -- the single biggest accuracy lever."""

from __future__ import annotations

import pytest

from pipeline.model.supply import (
    CF_BOUNDS, DEFAULT_CF, HOURS_PER_YEAR, annual_generation, calibrate, online_fraction,
)
from pipeline.provenance import Kind, measured
from pipeline.schema import Asset, AssetKind, Fuel, Status


def plant(mw: float, fuel=Fuel.COAL, country="XYZ", commissioned=None, retired=None,
          status=Status.OPERATING) -> Asset:
    return Asset(
        id=f"t:{mw}:{country}:{fuel.value}", kind=AssetKind.GENERATION, name="t",
        country=country, lat=0.0, lon=0.0,
        fuel=measured(fuel, "wri_gppd"), status=measured(status, "wri_gppd"),
        capacity_mw=measured(mw, "wri_gppd"),
        commissioned=measured(commissioned, "wri_gppd") if commissioned else None,
        retired=measured(retired, "wri_gppd") if retired else None,
    )


class FakeEmber:
    def __init__(self, generation, total=None):
        self.year = 2019
        self.generation = generation
        self.total_generation = total or {}


def test_calibration_reproduces_reported_generation():
    """The whole point: modelled national output must match what was reported."""
    assets = [plant(1000), plant(500)]
    reported = 1500 * HOURS_PER_YEAR * 0.6 / 1000  # a 0.6 capacity factor
    cal = calibrate(assets, FakeEmber({("XYZ", Fuel.COAL): reported}))

    cf, defaulted = cal.factor("XYZ", Fuel.COAL)
    assert not defaulted
    assert cf == pytest.approx(0.6, abs=1e-6)
    total = sum(annual_generation(a, cal).value for a in assets)
    assert total == pytest.approx(reported, rel=1e-6)


def test_capacity_factors_differ_by_country_for_the_same_fuel():
    """A German PV farm really does run at about half a Nevada one. Calibration
    must recover that rather than flatten it to one global number."""
    assets = [plant(1000, Fuel.SOLAR, "DEU"), plant(1000, Fuel.SOLAR, "USA")]
    cal = calibrate(assets, FakeEmber({
        ("DEU", Fuel.SOLAR): 1000 * HOURS_PER_YEAR * 0.11 / 1000,
        ("USA", Fuel.SOLAR): 1000 * HOURS_PER_YEAR * 0.25 / 1000,
    }))
    assert cal.factor("DEU", Fuel.SOLAR)[0] == pytest.approx(0.11, abs=1e-6)
    assert cal.factor("USA", Fuel.SOLAR)[0] == pytest.approx(0.25, abs=1e-6)


def test_missing_country_falls_back_to_default_and_says_so():
    cal = calibrate([plant(100, Fuel.WIND, "ZZZ")], FakeEmber({}))
    cf, defaulted = cal.factor("ZZZ", Fuel.WIND)
    assert defaulted
    assert cf == DEFAULT_CF[Fuel.WIND]


def test_implausible_factors_are_clamped_and_recorded():
    """A capacity factor above 1 is impossible; it means the inventory and the
    reported generation disagree. Clamp, and surface it as a data-quality signal."""
    assets = [plant(10, Fuel.SOLAR, "AAA")]  # tiny capacity, huge reported output
    cal = calibrate(assets, FakeEmber({("AAA", Fuel.SOLAR): 10_000}))
    cf, _ = cal.factor("AAA", Fuel.SOLAR)
    assert cf == CF_BOUNDS[Fuel.SOLAR][1]
    assert ("AAA", Fuel.SOLAR) in cal.clamped
    assert cal.clamp_rate == 1.0


def test_retired_and_unbuilt_plants_do_not_generate():
    cal = calibrate([plant(100)], FakeEmber({}))
    assert annual_generation(plant(100, status=Status.RETIRED), cal) is None
    assert annual_generation(plant(100, status=Status.ANNOUNCED), cal) is None


def test_online_fraction_handles_partial_years():
    """Without this, a new build overstates its first year and calibration pushes
    everyone else's capacity factor down to compensate."""
    assert online_fraction(plant(1, commissioned=2010), 2019) == 1.0
    assert online_fraction(plant(1, commissioned=2025), 2019) == 0.0
    assert online_fraction(plant(1, commissioned=2019), 2019) == 0.5
    assert online_fraction(plant(1, retired=2015), 2019) == 0.0
    assert online_fraction(plant(1, retired=2019), 2019) == 0.5


def test_generation_is_marked_derived_and_cites_both_inputs():
    """It is computed from capacity and calibrated against Ember, so it must
    read as an estimate and name both sources."""
    cal = calibrate([plant(100)], FakeEmber({("XYZ", Fuel.COAL): 100}))
    g = annual_generation(plant(100), cal)
    assert g is not None
    assert g.kind is Kind.DERIVED
    assert g.method == "supply.calibrated_capacity_factor"
    assert "ember_yearly" in g.via


def test_worst_divergences_are_ranked_by_magnitude():
    cal = calibrate([plant(1000, Fuel.COAL, "AAA"), plant(1000, Fuel.COAL, "BBB")],
                    FakeEmber({}, total={"AAA": 1e9, "BBB": 4000}))
    worst = cal.worst_divergences(2)
    assert worst[0][0] == "AAA"
