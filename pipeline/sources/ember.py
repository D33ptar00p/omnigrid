"""Read Ember's yearly electricity data: the calibration target.

Ember reports what each country actually generated, by fuel. Reconciling our
capacity-derived estimates against it is the single biggest accuracy lever in the
model -- bigger than any refinement of the allocation itself -- because it is what
makes a German solar farm and a Nevada one differ by the amount they really do.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.schema import Fuel

SOURCE_ID = "ember_yearly"

#: Ember's fuel variables -> our taxonomy. Ember has no geothermal line; its
#: "Other Renewables" is predominantly geothermal plus marine, and its
#: "Other Fossil" is predominantly oil.
FUEL_VARIABLE: dict[str, Fuel] = {
    "Coal": Fuel.COAL,
    "Gas": Fuel.GAS,
    "Other Fossil": Fuel.OIL,
    "Nuclear": Fuel.NUCLEAR,
    "Hydro": Fuel.HYDRO,
    "Wind": Fuel.WIND,
    "Solar": Fuel.SOLAR,
    "Bioenergy": Fuel.BIOENERGY,
    "Other Renewables": Fuel.GEOTHERMAL,
}


@dataclass
class EmberData:
    """Per-country annual figures, keyed by ISO3."""

    year: int
    #: (iso3, Fuel) -> generation GWh
    generation: dict[tuple[str, Fuel], float] = field(default_factory=dict)
    #: iso3 -> total generation GWh
    total_generation: dict[str, float] = field(default_factory=dict)
    #: iso3 -> demand GWh
    demand: dict[str, float] = field(default_factory=dict)
    #: iso3 -> net imports GWh (positive = importing)
    net_imports: dict[str, float] = field(default_factory=dict)
    #: iso3 -> gCO2/kWh, used to sanity-check our own emissions arithmetic
    co2_intensity: dict[str, float] = field(default_factory=dict)

    @property
    def countries(self) -> set[str]:
        return set(self.total_generation)

    def fuel_mix(self, iso3: str) -> dict[Fuel, float]:
        return {f: g for (c, f), g in self.generation.items() if c == iso3 and g > 0}


def read(path: Path, year: int | None = None) -> EmberData:
    """Parse the long-format CSV, taking the most recent year unless told otherwise."""
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["Area type"] != "Country" or not r["Country code"]:
                continue
            rows.append(r)

    if year is None:
        year = max(int(r["Year"]) for r in rows)

    data = EmberData(year=year)
    twh_gen: dict[tuple[str, Fuel], float] = defaultdict(float)

    for r in rows:
        if int(r["Year"]) != year:
            continue
        iso3, var, unit = r["Country code"], r["Variable"], r["Unit"]
        try:
            value = float(r["Value"])
        except (TypeError, ValueError):
            continue

        cat, sub = r["Category"], r["Subcategory"]
        if cat == "Electricity generation" and sub == "Fuel" and unit == "TWh":
            if (fuel := FUEL_VARIABLE.get(var)) is not None:
                # Several Ember variables can map to one of our fuels; sum them.
                twh_gen[(iso3, fuel)] += value
        elif cat == "Electricity generation" and var == "Total generation" and unit == "TWh":
            data.total_generation[iso3] = value * 1000
        elif cat == "Electricity demand" and sub == "Demand" and unit == "TWh":
            data.demand[iso3] = value * 1000
        elif cat == "Electricity imports" and unit == "TWh":
            data.net_imports[iso3] = value * 1000
        elif sub == "CO2 intensity" and unit == "gCO2 per kWh":
            data.co2_intensity[iso3] = value

    data.generation = {k: v * 1000 for k, v in twh_gen.items()}  # TWh -> GWh
    return data
