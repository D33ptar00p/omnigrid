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
from pipeline import pack
from pipeline.schema import Asset, Fuel
from pipeline import gb as gb_build
from pipeline.sources import gb as gb_src, gem, wri
from pipeline.sources.fetch import MissingVendoredInput, fetch
from pipeline.sources.registry import Registry, load

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "data" / "dist"
RAW = ROOT / "data" / "raw"


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
    gb: dict[str, object] = field(default_factory=dict)
    packed: dict[str, object] = field(default_factory=dict)
    #: Caveats, each tagged with the view it concerns, so the banner can show
    #: only what is true of what you are currently looking at.
    warnings: list[dict[str, str]] = field(default_factory=list)

    def warn(self, scope: str, text: str) -> None:
        self.warnings.append({"scope": scope, "text": " ".join(text.split())})
    degraded: bool = False


    def summarise(self, assets: list[Asset]) -> None:
        self.assets = len(assets)
        for a in assets:
            f = a.fuel.value.value
            self.by_fuel[f] = self.by_fuel.get(f, 0) + 1
            if a.capacity_mw:
                self.capacity_gw += a.capacity_mw.value / 1000


def load_assets(reg: Registry, bm: mf.BuildManifest, report: BuildReport) -> list[Asset]:
    """Primary path is GEM. Falls back to WRI when the form-gated GEM workbook
    has not been vendored, and says so loudly rather than pretending."""
    allow_degraded = os.environ.get("OMNIGRID_ALLOW_DEGRADED") == "1"
    try:
        got = fetch(reg["gem_gipt"])
    except MissingVendoredInput as e:
        if not allow_degraded:
            raise BuildFailed(str(e)) from None
        report.degraded = True
        report.warn(
            "world",
            "DEGRADED BUILD: Global Energy Monitor data not vendored. The World tab "
            "falls back to WRI GPPD v1.3.0 (unmaintained since 2021, ~35k plants "
            "instead of ~145k). GEM's download is behind a name/email form, so it "
            "cannot be fetched automatically: drop the .xlsx into data/raw/gem/ and "
            "rebuild. This does not affect the Great Britain view.",
        )
    else:
        bm.record_input("gem_gipt", got.path)
        assets, skipped = gem.read(got.path)
        _check_unmapped(skipped)
        report.skipped |= skipped
        return assets

    got = fetch(reg["wri_gppd"])
    bm.record_input("wri_gppd", got.path)
    assets, skipped = wri.read(got.path)
    _check_unmapped(skipped)
    report.skipped |= skipped
    return assets


def _check_unmapped(skipped: dict[str, int]) -> None:
    """An unmapped fuel is a gap to close, not rows to drop quietly."""
    for reason, n in skipped.items():
        if reason.startswith(("UNMAPPED", "unmapped")):
            raise BuildFailed(f"{n} row(s) with an unmapped value: {reason}")


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

    # --- Great Britain: measured generation on the published network --------
    for sid in ("elexon_bmu", "elexon_b1610", "neso_dno_areas", "osm_gb_power"):
        got = fetch(reg[sid])
        bm.record_input(sid, got.path)
    if (RAW / "wikidata" / "images.json").exists():
        bm.record_input("wikidata", RAW / "wikidata" / "images.json")
    settlement_date, period = gb_src.recent_settlement_period()
    bm.record_data_date("elexon_b1610", f"{settlement_date}, settlement period {period}")
    gb_report = gb_build.build(RAW, dist / "gb",
                               settlement=f"{settlement_date} period {period}")
    report.gb = {
        "plants": gb_report.plants,
        "gb_plants": gb_report.gb_plants,
        "offshore_capacity_gw": round(gb_report.offshore_capacity_gw, 1),
        "plants_capacity_gw": round(gb_report.plants_capacity_gw, 1),
        "units_transmission": gb_report.units_transmission,
        "units_embedded": gb_report.units_embedded,
        "interconnectors": gb_report.interconnectors,
        "regions": gb_report.regions,
        "matched": gb_report.matched,
        "with_image": gb_report.with_image,
        "lines": gb_report.lines,
        "plants_wired": gb_report.plants_wired,
        "operator_linked": gb_report.operator_linked,
        "offshore": gb_report.offshore,
        "metered_gw": round(gb_report.metered_gw, 1),
        "settlement": gb_report.settlement,
    }
    for note in gb_report.notes:
        report.warn("gb", note)

    cited = collect_source_ids(assets) | bm.used
    if problems := mf.check(reg, cited):
        raise BuildFailed("provenance check failed:\n  - " + "\n  - ".join(problems))
    bm.record_use(*cited)

    dist.mkdir(parents=True, exist_ok=True)
    packed = pack.write(assets, dist)
    report.packed = {
        "count": packed.count,
        "points_mb": round(packed.bytes_points / 1e6, 1),
        "detail_mb": round(packed.bytes_detail / 1e6, 1),
    }

    bm.warnings = report.warnings
    bm.model_params = {"degraded": report.degraded}
    bm.validation = {"gb": report.gb}
    bm.write(reg, dist)
    mf.write_attribution(reg, bm.used)

    # Legend/palette ordering is data, not a frontend constant, so the two cannot
    # disagree about which fuels exist.
    (dist / "fuels.json").write_text(
        json.dumps([f.value for f in Fuel], indent=1) + "\n"
    )
    return report


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Build the OmniGrid data payload.")
    ap.parse_args()

    try:
        r = run()
    except BuildFailed as e:
        print(f"\nBUILD FAILED\n{e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{r.assets:,} assets  ·  {r.capacity_gw:,.0f} GW")
    if r.packed:
        print(f"  packed: {r.packed['points_mb']} MB render + "
              f"{r.packed['detail_mb']} MB detail on demand")
    for f, n in sorted(r.by_fuel.items(), key=lambda x: -x[1]):
        print(f"  {f:12} {n:7,}")
    if r.skipped:
        print("\nskipped:", dict(r.skipped))
    if r.gb:
        g = r.gb
        print(f"\nGreat Britain (measured):")
        print(f"  {g['gb_plants']:,} GB plants surveyed in OSM · "
              f"{g['plants_capacity_gw']} GW "
              f"(of {g['plants']:,} in bounds; the rest are on other grids)")
        print(f"  {g['units_transmission']} transmission units · "
              f"{g['units_embedded']} embedded · {g['interconnectors']} interconnectors")
        print(f"  {g['regions']} DNO regions · {g['matched']} OSM↔Elexon name matches")
        print(f"  {g['with_image']} plants with a photograph")
        if g.get("lines"):
            print(f"  {g.get('offshore', 0)} offshore · "
                  f"{g.get('offshore_capacity_gw', 0)} GW")
            print(f"  {g['lines']:,} transmission lines · "
                  f"{g['plants_wired']:,} plants traced to the network")
        print(f"  metered output {g['metered_gw']} GW ({g['settlement']})")
    for w in r.warnings:
        print(f"\n!! [{w['scope']}] {w['text']}")
    print(f"\nwrote data/dist/  ({sum(p.stat().st_size for p in DIST.iterdir())/1e6:.1f} MB)")
