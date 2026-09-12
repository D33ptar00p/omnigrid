"""Estimate what each plant actually generates in a year.

    s_j = capacity_MW x 8766 h x CF(fuel, country) x online_fraction / 1000  [GWh]

The capacity factors are *calibrated*, not assumed: for each country and fuel we
solve for the CF that makes our summed estimate match Ember's reported national
generation. This is the single biggest accuracy lever in the whole model. It is
also where solar and wind legitimately differentiate -- a German PV farm really
does run at roughly half the capacity factor of a Nevada one, and calibration
recovers that from reported data rather than inventing it.

Where Ember has no figure for a country/fuel, a global default is used and the
result is flagged, so the UI can desaturate what rests on an assumption.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pipeline.provenance import derived
from pipeline.schema import Asset, Fuel

HOURS_PER_YEAR = 8766  # 365.25 x 24

#: Global default capacity factors, used only where calibration is impossible.
#: Deliberately mid-range: these should look wrong enough to notice if they ever
#: dominate a country's figures.
DEFAULT_CF: dict[Fuel, float] = {
    Fuel.COAL: 0.55, Fuel.OIL: 0.30, Fuel.GAS: 0.40, Fuel.NUCLEAR: 0.80,
    Fuel.HYDRO: 0.40, Fuel.WIND: 0.28, Fuel.SOLAR: 0.14, Fuel.GEOTHERMAL: 0.75,
    Fuel.BIOENERGY: 0.50, Fuel.OTHER: 0.30,
}

#: Physically plausible bounds. A calibrated CF outside these means the capacity
#: inventory disagrees with Ember badly enough that the fault is in the data, not
#: the plant -- clamp, and record that we did.
CF_BOUNDS: dict[Fuel, tuple[float, float]] = {
    Fuel.COAL: (0.05, 0.95), Fuel.OIL: (0.01, 0.90), Fuel.GAS: (0.02, 0.95),
    Fuel.NUCLEAR: (0.20, 1.00), Fuel.HYDRO: (0.05, 0.85), Fuel.WIND: (0.05, 0.65),
    Fuel.SOLAR: (0.03, 0.40), Fuel.GEOTHERMAL: (0.10, 0.98),
    Fuel.BIOENERGY: (0.05, 0.95), Fuel.OTHER: (0.01, 0.95),
}

METHOD = "supply.calibrated_capacity_factor"

#: Reference year for the degraded (WRI) build. WRI v1.3.0's capacity is dated
#: 2019 for the plurality of plants that state a year at all, and 20,049 of
#: 34,801 state none. Calibrating 2019 capacity against 2022 generation would
#: charge the inventory for five years of solar and wind build-out it never saw,
#: pinning those capacity factors at their upper bounds. 2019 also gives the
#: best country coverage in Ember (94%).
WRI_REFERENCE_YEAR = 2019


@dataclass
class Calibration:
    """Capacity factors plus an account of how well they reconcile."""

    year: int
    cf: dict[tuple[str, Fuel], float] = field(default_factory=dict)
    #: (iso3, fuel) pairs that fell back to a global default.
    defaulted: set[tuple[str, Fuel]] = field(default_factory=set)
    #: (iso3, fuel) -> (raw_cf, clamped_cf) where bounds bit.
    clamped: dict[tuple[str, Fuel], tuple[float, float]] = field(default_factory=dict)
    #: iso3 -> (modelled GWh, Ember GWh) after calibration, for the QA report.
    reconciliation: dict[str, tuple[float, float]] = field(default_factory=dict)

    def factor(self, iso3: str, fuel: Fuel) -> tuple[float, bool]:
        """Return (capacity_factor, is_default)."""
        key = (iso3, fuel)
        if key in self.cf:
            return self.cf[key], key in self.defaulted
        return DEFAULT_CF[fuel], True

    @property
    def coverage(self) -> float:
        """Share of country/fuel pairs backed by reported data rather than a default."""
        return 1 - len(self.defaulted) / len(self.cf) if self.cf else 0.0

    @property
    def clamp_rate(self) -> float:
        """Share of pairs whose calibrated factor was physically implausible.

        This is a data-quality signal, not a modelling knob: a high rate means the
        capacity inventory and reported generation genuinely disagree, and every
        figure resting on those pairs deserves a caveat.
        """
        return len(self.clamped) / len(self.cf) if self.cf else 0.0

    def worst_divergences(self, n: int = 10) -> list[tuple[str, float, float, float]]:
        """Countries where modelled and reported national totals disagree most.
        Returned so the build can publish them rather than quietly reconciling."""
        out = []
        for iso3, (modelled, reported) in self.reconciliation.items():
            if reported > 0:
                out.append((iso3, modelled, reported, modelled / reported - 1))
        return sorted(out, key=lambda r: -abs(r[3]))[:n]


def online_fraction(asset: Asset, year: int) -> float:
    """How much of the reference year the plant was actually running.

    A plant commissioned in July contributes half a year. Without this, every new
    build overstates its first-year output, and calibration pushes everyone else's
    capacity factor down to compensate.
    """
    start = asset.commissioned.value if asset.commissioned else None
    end = asset.retired.value if asset.retired else None
    if start is not None and start > year:
        return 0.0
    if end is not None and end < year:
        return 0.0
    # Mid-year commissioning/retirement: half a year, absent monthly detail.
    if start == year or end == year:
        return 0.5
    return 1.0


def calibrate(assets: list[Asset], ember, *, year: int | None = None) -> Calibration:
    """Solve for the capacity factor that reproduces reported national generation.

    Inverting  GWh = MW x 8.766 x CF  gives  CF = GWh / (MW x 8.766), so the
    calibration is direct rather than iterative.
    """
    year = year or ember.year
    cal = Calibration(year=year)

    # Effective capacity: only operating plants, weighted by their online fraction.
    capacity: dict[tuple[str, Fuel], float] = defaultdict(float)
    for a in assets:
        if not a.capacity_mw or not a.status.value.counts_as_supply:
            continue
        frac = online_fraction(a, year)
        if frac > 0:
            capacity[(a.country, a.fuel.value)] += a.capacity_mw.value * frac

    for key, mw in capacity.items():
        iso3, fuel = key
        reported = ember.generation.get(key)
        if reported is None or reported <= 0 or mw <= 0:
            cal.cf[key] = DEFAULT_CF[fuel]
            cal.defaulted.add(key)
            continue

        raw = reported / (mw * HOURS_PER_YEAR / 1000)
        lo, hi = CF_BOUNDS[fuel]
        clamped = min(max(raw, lo), hi)
        if clamped != raw:
            cal.clamped[key] = (raw, clamped)
        cal.cf[key] = clamped

    # Reconciliation after clamping: where this diverges, the capacity inventory
    # and Ember disagree, and that is worth reporting rather than hiding.
    modelled: dict[str, float] = defaultdict(float)
    for key, mw in capacity.items():
        modelled[key[0]] += mw * HOURS_PER_YEAR * cal.cf[key] / 1000
    for iso3, m in modelled.items():
        if (r := ember.total_generation.get(iso3)):
            cal.reconciliation[iso3] = (m, r)
    return cal


def annual_generation(asset: Asset, cal: Calibration):
    """Attach a derived, cited generation estimate to one asset."""
    if not asset.capacity_mw or not asset.status.value.counts_as_supply:
        return None
    frac = online_fraction(asset, cal.year)
    if frac <= 0:
        return None
    cf, _ = cal.factor(asset.country, asset.fuel.value)
    gwh = asset.capacity_mw.value * HOURS_PER_YEAR * cf * frac / 1000
    return derived(round(gwh, 2), METHOD, asset.capacity_mw.source_id, "ember_yearly")
