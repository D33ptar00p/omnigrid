"""Normalise every source into one asset set and write the distributable payload.

Runs the provenance gate before writing: if any value cites a source the registry
does not know, or a source with an unresolved licence, the build fails rather than
shipping a number nobody can trace.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from pipeline import manifest as mf
from pipeline.provenance import collect_source_ids, derived
from pipeline.model import supply
from pipeline.schema import Asset, Fuel
from pipeline.sources import ember, regions, wri
from pipeline.sources.fetch import MissingVendoredInput, fetch
from pipeline.sources.registry import Registry, load

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "data" / "dist"


class BuildFailed(Exception):
    pass


@dataclass
class BuildReport:
    """What the build actually did. Printed, and shipped inside manifest.json, so
    dropped rows and source disagreements are visible rather than lost."""

    assets: int = 0
    by_fuel: dict[str, int] = field(default_factory=dict)
    capacity_gw: float = 0.0
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    generation_twh: float = 0.0
    calibration: dict[str, object] = field(default_factory=dict)
    by_region: dict[str, int] = field(default_factory=dict)

    def summarise(self, assets: list[Asset]) -> None:
        self.assets = len(assets)
        for a in assets:
            f = a.fuel.value.value
            self.by_fuel[f] = self.by_fuel.get(f, 0) + 1
            if a.capacity_mw:
                self.capacity_gw += a.capacity_mw.value / 1000


def load_assets(reg: Registry, bm: mf.BuildManifest, report: BuildReport) -> list[Asset]:
    """Primary path is GEM. Falls back to WRI + OSM when the form-gated GEM files
    have not been vendored, and says so loudly rather than pretending."""
    allow_degraded = os.environ.get("OMNIGRID_ALLOW_DEGRADED") == "1"
    try:
        fetch(reg["gem_gipt"])
    except MissingVendoredInput as e:
        if not allow_degraded:
            raise BuildFailed(str(e)) from None
        report.degraded = True
        report.warnings.append(
            "DEGRADED BUILD: Global Energy Monitor data not vendored. Falling back to "
            "WRI GPPD v1.3.0 (unmaintained since 2021, ~35k plants instead of ~182k). "
            "The UI must show this."
        )
    else:
        raise NotImplementedError("GEM reader lands in the next step")

    got = fetch(reg["wri_gppd"])
    bm.record_input("wri_gppd", got.path)
    assets, skipped = wri.read(got.path)
    report.skipped |= skipped
    for reason, n in skipped.items():
        if reason.startswith("UNMAPPED FUEL"):
            raise BuildFailed(f"{n} row(s) with unmapped fuel: {reason}")
    return assets


def enrich(assets: list[Asset], reg, bm: mf.BuildManifest, report: BuildReport) -> None:
    """Attach the two things the map needs beyond the raw inventory: which
    synchronous grid each asset sits in, and what it actually generates."""
    got = fetch(reg["ember_yearly"])
    bm.record_input("ember_yearly", got.path)
    year = supply.WRI_REFERENCE_YEAR if report.degraded else None
    em = ember.read(got.path, year=year)
    cal = supply.calibrate(assets, em, year=year)

    index = regions.load()
    bm.record_use(regions.SOURCE_ID)

    for a in assets:
        region_id, approximate = index.assign(a.country, a.lat, a.lon)
        a.extra["region"] = derived(
            index.label(region_id), "regions.assign", regions.SOURCE_ID)
        if approximate:
            # Surfaced so the UI can desaturate what rests on a geographic rule
            # rather than a real boundary.
            a.extra["region_approximate"] = derived(
                True, "regions.geographic_rule", regions.SOURCE_ID)
        a.extra["region_id"] = derived(region_id, "regions.assign", regions.SOURCE_ID)

        # Our calibrated estimate becomes primary; whatever the source reported
        # is kept alongside it so the two can be compared rather than merged.
        if (reported := a.generation_gwh) is not None:
            a.extra["generation_reported_gwh"] = reported
        if (est := supply.annual_generation(a, cal)) is not None:
            a.generation_gwh = est
            report.generation_twh += est.value / 1000

        cf, defaulted = cal.factor(a.country, a.fuel.value)
        if defaulted:
            a.extra["capacity_factor_assumed"] = derived(
                round(cf, 3), "supply.default_capacity_factor", "ember_yearly")

    for a in assets:
        r = str(a.extra["region"].value)
        report.by_region[r] = report.by_region.get(r, 0) + 1

    report.calibration = {
        "year": cal.year,
        "pairs": len(cal.cf),
        "coverage": round(cal.coverage, 3),
        "clamp_rate": round(cal.clamp_rate, 3),
        "worst_divergences": [
            {"country": c, "modelled_gwh": round(m), "reported_gwh": round(r),
             "divergence": round(d, 3)}
            for c, m, r, d in cal.worst_divergences(15)
        ],
    }
    if cal.clamp_rate > 0.15:
        report.warnings.append(
            f"CAPACITY FACTORS: {cal.clamp_rate:.0%} of country/fuel pairs produced a "
            "physically implausible capacity factor and were clamped. The capacity "
            "inventory and reported generation disagree; figures resting on those "
            "pairs are weak."
        )


def to_geojson(assets: list[Asset]) -> dict:
    """Points for the map. Citations ride along per feature so the detail panel can
    show, per field, which dataset said it and whether it is measured or estimated."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": i,
                "geometry": {"type": "Point", "coordinates": [round(a.lon, 5), round(a.lat, 5)]},
                "properties": {
                    **a.to_json(),
                    # Flat duplicates of the two fields the map style filters and
                    # sizes on. MapLibre expressions cannot reach into the nested
                    # Cited objects, and doing this in the browser would mean
                    # rewriting every feature on load.
                    "_fuel": a.fuel.value.value,
                    "_mw": round(a.capacity_mw.value, 1) if a.capacity_mw else 0,
                },
            }
            for i, a in enumerate(assets)
        ],
    }


def run(dist: Path = DIST) -> BuildReport:
    reg = load()
    bm = mf.BuildManifest()
    report = BuildReport()

    assets = load_assets(reg, bm, report)
    enrich(assets, reg, bm, report)
    report.summarise(assets)

    # --- provenance gate: nothing ships that cannot be traced -----------------
    cited = collect_source_ids(assets)
    bm.record_use(*cited)
    if problems := mf.check(reg, bm.used):
        raise BuildFailed("provenance check failed:\n  - " + "\n  - ".join(problems))

    dist.mkdir(parents=True, exist_ok=True)
    (dist / "assets.geojson").write_text(json.dumps(to_geojson(assets), separators=(",", ":")))

    bm.warnings = report.warnings
    bm.model_params = {"degraded": report.degraded}
    bm.validation = {"calibration": report.calibration}
    bm.write(reg, dist)
    mf.write_attribution(reg, bm.used)

    # Legend/palette ordering is data, not a frontend constant, so the two cannot
    # disagree about which fuels exist.
    (dist / "fuels.json").write_text(
        json.dumps([f.value for f in Fuel], indent=1) + "\n"
    )
    return report


if __name__ == "__main__":
    import sys

    try:
        r = run()
    except BuildFailed as e:
        print(f"\nBUILD FAILED\n{e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{r.assets:,} assets  ·  {r.capacity_gw:,.0f} GW  ·  "
          f"{r.generation_twh:,.0f} TWh/yr modelled")
    for f, n in sorted(r.by_fuel.items(), key=lambda x: -x[1]):
        print(f"  {f:12} {n:7,}")
    c = r.calibration
    print(f"\ncalibration {c['year']}: {c['pairs']} country/fuel pairs, "
          f"{c['coverage']:.0%} from reported data, {c['clamp_rate']:.0%} clamped")
    print("\ntop regions:")
    for name, n in sorted(r.by_region.items(), key=lambda x: -x[1])[:6]:
        print(f"  {name:34} {n:6,}")
    if r.skipped:
        print("\nskipped:", dict(r.skipped))
    for w in r.warnings:
        print(f"\n!! {w}")
    print(f"\nwrote data/dist/  ({sum(p.stat().st_size for p in DIST.iterdir())/1e6:.1f} MB)")
