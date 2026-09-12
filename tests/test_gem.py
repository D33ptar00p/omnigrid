"""The Global Energy Monitor tracker: the primary global source.

Unit-level rows grouped into plants. These tests pin the grouping and the two
places the mapping could quietly go wrong — the oil/gas split and the status
roll-up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.schema import Fuel, Status, UnknownFuel
from pipeline.sources.gem import _fuel, _status, _first_party

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "gem"
WORKBOOK = next(RAW.glob("*Integrated*Power*.xlsx"), None)


def test_oil_gas_is_split_by_fuel_classification():
    """GEM's Type column calls both "oil/gas"; they burn very differently and
    must not be merged."""
    assert _fuel("oil/gas", "Gas") is Fuel.GAS
    assert _fuel("oil/gas", "LNG only") is Fuel.GAS
    assert _fuel("oil/gas", "Oil") is Fuel.OIL
    # Multi-fuel plants run on gas in practice.
    assert _fuel("oil/gas", "Multi Fuel") is Fuel.GAS
    # Missing classification defaults to gas rather than raising: the Type is
    # known, only the split is not.
    assert _fuel("oil/gas", None) is Fuel.GAS


def test_unmapped_values_raise_rather_than_defaulting():
    with pytest.raises(UnknownFuel, match="unmapped GEM Type"):
        _fuel("antimatter", None)
    with pytest.raises(UnknownFuel, match="oil/gas classification"):
        _fuel("oil/gas", "Unobtainium")


@pytest.mark.parametrize("raw,expected", [
    ("operating", Status.OPERATING),
    ("construction", Status.CONSTRUCTION),
    ("pre-construction", Status.ANNOUNCED),
    ("retired", Status.RETIRED),
    ("mothballed", Status.MOTHBALLED),
    ("cancelled", Status.CANCELLED),
    ("shelved", Status.CANCELLED),
    # GEM appends inference notes to some statuses.
    ("cancelled - inferred 4 y", Status.CANCELLED),
    ("shelved - inferred 2 y", Status.CANCELLED),
])
def test_status_mapping_including_inferred_suffixes(raw, expected):
    assert _status(raw) is expected


def test_owner_shares_are_reduced_to_the_first_party():
    assert _first_party("Ingenio Palo Gordo SA [100%]") == "Ingenio Palo Gordo SA"
    assert _first_party("A Ltd [60%]; B Ltd [40%]") == "A Ltd"
    assert _first_party(None) is None
    assert _first_party("") is None


@pytest.mark.skipif(WORKBOOK is None, reason="GEM workbook not vendored")
class TestWorkbook:
    @pytest.fixture(scope="class")
    def parsed(self):
        from pipeline.sources.gem import read

        return read(WORKBOOK)

    def test_units_are_grouped_into_plants(self, parsed):
        """183,125 unit rows collapse to 145,396 plants. Without grouping, a
        six-unit coal station is six dots on the same pixel."""
        assets, _ = parsed
        assert 100_000 < len(assets) < 183_125

    def test_nothing_is_skipped_silently(self, parsed):
        _, skipped = parsed
        unmapped = {k: v for k, v in skipped.items() if k.startswith("UNMAPPED")}
        assert not unmapped, f"unmapped values: {unmapped}"

    def test_capacity_total_matches_what_gem_publishes(self, parsed):
        """GEM states roughly 22,300 GW across the tracker."""
        assets, _ = parsed
        gw = sum(a.capacity_mw.value for a in assets if a.capacity_mw) / 1000
        assert 20_000 < gw < 25_000, f"{gw:,.0f} GW"

    def test_every_plant_has_usable_coordinates(self, parsed):
        assets, _ = parsed
        for a in assets:
            assert -90 <= a.lat <= 90 and -180 <= a.lon <= 180, a.name

    def test_a_known_plant_reads_correctly(self, parsed):
        """Three Gorges: 22.5 GW, hydro, operating."""
        assets, _ = parsed
        three_gorges = [a for a in assets if "Three Gorges Dam" in a.name]
        assert three_gorges
        plant = max(three_gorges, key=lambda a: a.capacity_mw.value if a.capacity_mw else 0)
        assert plant.fuel.value is Fuel.HYDRO
        assert plant.status.value is Status.OPERATING
        assert 20_000 < plant.capacity_mw.value < 25_000

    def test_every_value_is_measured(self, parsed):
        """Nothing derived may enter from this source."""
        from pipeline.provenance import Kind

        assets, _ = parsed
        for a in assets[:5000]:
            for name, cited in a.cited_fields().items():
                assert cited.kind is Kind.MEASURED, f"{a.name}.{name}"
