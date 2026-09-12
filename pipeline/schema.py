"""The unified asset schema and the fuel taxonomy.

The taxonomy is deliberately *total*: every source value maps to a known Fuel, and
an unrecognised one raises rather than quietly becoming OTHER. Silent fallthrough
here would be invisible in the UI and would corrupt the capacity-factor calibration,
because "other" has no defensible capacity factor or emissions factor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pipeline.provenance import Cited


class Fuel(str, Enum):
    """The ten categories that drive colour, capacity factors and emissions."""

    COAL = "coal"
    OIL = "oil"
    GAS = "gas"
    NUCLEAR = "nuclear"
    HYDRO = "hydro"
    WIND = "wind"
    SOLAR = "solar"
    GEOTHERMAL = "geothermal"
    BIOENERGY = "bioenergy"
    OTHER = "other"

    @property
    def is_fossil(self) -> bool:
        return self in (Fuel.COAL, Fuel.OIL, Fuel.GAS)

    @property
    def is_renewable(self) -> bool:
        return self in (Fuel.HYDRO, Fuel.WIND, Fuel.SOLAR, Fuel.GEOTHERMAL, Fuel.BIOENERGY)


class AssetKind(str, Enum):
    """Generation makes electricity; extraction pulls fuel out of the ground.

    Kept distinct because they get different symbology and because an oil field has
    no capacity in MW and therefore no supply shed.
    """

    GENERATION = "generation"
    EXTRACTION = "extraction"


class Status(str, Enum):
    OPERATING = "operating"
    CONSTRUCTION = "construction"
    ANNOUNCED = "announced"
    RETIRED = "retired"
    MOTHBALLED = "mothballed"
    CANCELLED = "cancelled"

    @property
    def counts_as_supply(self) -> bool:
        """Only operating plants generate. Including announced units fabricates
        supply; leaving retired ones in fabricates it differently."""
        return self is Status.OPERATING


class UnknownFuel(ValueError):
    """An unmapped source value. Fatal: fix the taxonomy, don't guess."""


#: Source strings -> Fuel. Lowercased and stripped before lookup.
#: Covers WRI GPPD v1.3, GEM GIPT and common OSM `plant:source` values.
FUEL_ALIASES: dict[str, Fuel] = {
    # coal
    "coal": Fuel.COAL, "anthracite": Fuel.COAL, "bituminous": Fuel.COAL,
    "subbituminous": Fuel.COAL, "lignite": Fuel.COAL, "petcoke": Fuel.COAL,
    "coal gas": Fuel.COAL, "waste coal": Fuel.COAL,
    # oil
    "oil": Fuel.OIL, "petroleum": Fuel.OIL, "diesel": Fuel.OIL, "fuel oil": Fuel.OIL,
    "heavy fuel oil": Fuel.OIL, "light fuel oil": Fuel.OIL, "shale oil": Fuel.OIL,
    "oil/gas": Fuel.OIL,
    # gas
    "gas": Fuel.GAS, "natural gas": Fuel.GAS, "lng": Fuel.GAS, "fossil gas": Fuel.GAS,
    "coalbed methane": Fuel.GAS, "cogeneration": Fuel.GAS,
    # nuclear
    "nuclear": Fuel.NUCLEAR,
    # hydro
    "hydro": Fuel.HYDRO, "hydropower": Fuel.HYDRO, "water": Fuel.HYDRO,
    "run-of-river": Fuel.HYDRO, "reservoir": Fuel.HYDRO,
    "wave and tidal": Fuel.HYDRO, "tidal": Fuel.HYDRO, "wave": Fuel.HYDRO,
    # wind
    "wind": Fuel.WIND, "offshore wind": Fuel.WIND, "onshore wind": Fuel.WIND,
    # solar
    "solar": Fuel.SOLAR, "photovoltaic": Fuel.SOLAR, "pv": Fuel.SOLAR,
    "solar thermal": Fuel.SOLAR, "csp": Fuel.SOLAR,
    # geothermal
    "geothermal": Fuel.GEOTHERMAL,
    # bioenergy
    "biomass": Fuel.BIOENERGY, "bioenergy": Fuel.BIOENERGY, "biogas": Fuel.BIOENERGY,
    "waste": Fuel.BIOENERGY, "municipal solid waste": Fuel.BIOENERGY,
    "landfill gas": Fuel.BIOENERGY, "wood": Fuel.BIOENERGY, "bagasse": Fuel.BIOENERGY,
    "biofuel": Fuel.BIOENERGY, "landfill_gas": Fuel.BIOENERGY,
    "sewage gas": Fuel.BIOENERGY, "wastewater": Fuel.BIOENERGY,
    "sludge": Fuel.BIOENERGY,
    # UK-specific sources that appear in OpenStreetMap.
    "methane": Fuel.GAS, "mine gas": Fuel.GAS, "abandoned_mine_methane": Fuel.GAS,
    "coal_gas": Fuel.COAL, "waste_heat": Fuel.OTHER, "minewater": Fuel.OTHER,
    # explicitly other -- present in sources, genuinely unclassifiable
    "other": Fuel.OTHER, "unknown": Fuel.OTHER,
}

#: Excluded from generation supply entirely rather than mapped to a fuel.
#: Storage is negative-then-positive energy; counting it as generation inflates GW.
NON_GENERATING = {"storage", "battery", "pumped storage", "pumped hydro storage",
                  "compressed air", "flywheel", "liquid_air", "battery storage"}


def parse_fuel(raw: str | None) -> Fuel:
    """Map a source fuel string to the taxonomy, or raise.

    Raising on unknown values is the point: a silent OTHER would be invisible in
    the UI, and a plant whose fuel we cannot read is not a plant burning
    "other" -- it is a gap we should see and close.

    OpenStreetMap records multi-fuel plants as "oil;gas" or "biomass;waste". The
    first value is the primary source by convention, so it wins; the taxonomy
    has one slot per plant and inventing a blend would be worse.
    """
    if raw is None or not raw.strip():
        raise UnknownFuel("empty fuel value")
    key = raw.strip().lower()
    if ";" in key:
        key = key.split(";", 1)[0].strip()
    if key in NON_GENERATING:
        raise UnknownFuel(f"{raw!r} is storage, not generation -- exclude it upstream")
    try:
        return FUEL_ALIASES[key]
    except KeyError:
        raise UnknownFuel(
            f"unmapped fuel {raw!r}; add it to FUEL_ALIASES in pipeline/schema.py "
            "rather than letting it fall through to OTHER"
        ) from None


def is_non_generating(raw: str | None) -> bool:
    return bool(raw) and raw.strip().lower() in NON_GENERATING


STATUS_ALIASES: dict[str, Status] = {
    "operating": Status.OPERATING, "operational": Status.OPERATING, "active": Status.OPERATING,
    "construction": Status.CONSTRUCTION, "under construction": Status.CONSTRUCTION,
    "announced": Status.ANNOUNCED, "pre-construction": Status.ANNOUNCED,
    "permitted": Status.ANNOUNCED, "planned": Status.ANNOUNCED, "proposed": Status.ANNOUNCED,
    "retired": Status.RETIRED, "decommissioned": Status.RETIRED, "shut down": Status.RETIRED,
    "mothballed": Status.MOTHBALLED, "cancelled": Status.CANCELLED, "canceled": Status.CANCELLED,
    "shelved": Status.CANCELLED,
}


def parse_status(raw: str | None, default: Status = Status.OPERATING) -> Status:
    if raw is None or not raw.strip():
        return default
    return STATUS_ALIASES.get(raw.strip().lower(), default)


@dataclass(slots=True)
class Asset:
    """One power source. Fields that can vary by source are Cited, so the panel can
    say which dataset supplied each number and whether it is measured or estimated."""

    id: str
    kind: AssetKind
    name: str
    country: str                     # ISO3
    lat: float
    lon: float
    fuel: Cited[Fuel]
    status: Cited[Status]
    capacity_mw: Cited[float] | None = None
    owner: Cited[str] | None = None
    commissioned: Cited[int] | None = None
    retired: Cited[int] | None = None
    #: Estimated annual generation. DERIVED (Ember-calibrated capacity factor) or
    #: MEASURED where a source reports it.
    generation_gwh: Cited[float] | None = None
    extra: dict[str, Cited[Any]] = field(default_factory=dict)

    def cited_fields(self) -> dict[str, Cited[Any]]:
        out = {
            k: v
            for k in ("fuel", "status", "capacity_mw", "owner", "commissioned",
                      "retired", "generation_gwh")
            if (v := getattr(self, k)) is not None
        }
        return out | self.extra

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind.value, "name": self.name,
            "country": self.country, "lat": self.lat, "lon": self.lon,
            **{k: v.to_json() for k, v in self.cited_fields().items()},
        }
