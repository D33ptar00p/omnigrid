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
from pipeline.provenance import collect_source_ids
from pipeline.schema import Asset, Fuel
from pipeline.sources import wri
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

    print(f"\n{r.assets:,} assets  ·  {r.capacity_gw:,.0f} GW")
    for f, n in sorted(r.by_fuel.items(), key=lambda x: -x[1]):
        print(f"  {f:12} {n:7,}")
    if r.skipped:
        print("\nskipped:", dict(r.skipped))
    for w in r.warnings:
        print(f"\n!! {w}")
    print(f"\nwrote data/dist/  ({sum(p.stat().st_size for p in DIST.iterdir())/1e6:.1f} MB)")
