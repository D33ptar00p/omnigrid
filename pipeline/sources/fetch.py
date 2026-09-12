"""Fetch raw inputs, checksum them, and fail usefully when one must come by hand.

Most sources download unattended. The three Global Energy Monitor trackers sit
behind a name/email form, so they cannot be automated -- those are *vendored*:
fetched once by a human into data/raw/gem/ and checksummed thereafter. When one is
missing the failure names the file and the page to get it from, rather than
half-building something and going quiet about the hole.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import requests

from pipeline.sources.registry import Registry, Source, load, sha256

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
UA = "omnigrid/0.1 (open energy map; +https://github.com/omnigrid/omnigrid)"


class MissingVendoredInput(Exception):
    """A form-gated source is not present. Actionable by a human, not the pipeline."""


@dataclass(frozen=True, slots=True)
class Fetched:
    source_id: str
    path: Path
    sha256: str
    from_cache: bool


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": UA}) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            shutil.copyfileobj(r.raw, fh)
    tmp.replace(dest)  # atomic: a partial download never looks like a complete one


def find_vendored(source: Source, raw: Path = RAW) -> Path:
    """Locate a hand-placed file, or explain precisely how to supply it."""
    if not source.raw_glob:
        raise MissingVendoredInput(f"{source.id}: vendored but declares no raw_glob")
    matches = sorted(raw.glob(source.raw_glob))
    if not matches:
        raise MissingVendoredInput(
            f"\n  Missing required input: {source.name}\n"
            f"  Source id   : {source.id}\n"
            f"  Expected at : data/raw/{source.raw_glob}\n"
            f"  Get it from : {source.download_url or source.url}\n\n"
            f"  This dataset is behind a name/email form, so it cannot be downloaded\n"
            f"  automatically. Download it once, drop it in data/raw/gem/, and re-run.\n"
            f"  To build without it, run with OMNIGRID_ALLOW_DEGRADED=1 -- the map will\n"
            f"  fall back to WRI GPPD + OpenStreetMap and say so in the UI.\n"
        )
    if len(matches) > 1:
        # Ambiguity here silently picks a release; make the human choose.
        names = ", ".join(p.name for p in matches)
        raise MissingVendoredInput(
            f"{source.id}: {len(matches)} files match {source.raw_glob!r} ({names}). "
            "Keep exactly one so the build pins a known release."
        )
    return matches[0]


#: Sources that are API queries rather than a file at a URL. Each names the
#: local filename the pipeline expects, so a cached copy is reused and the build
#: does not hammer a public endpoint on every run.
QUERY_SOURCES = {
    "elexon_bmu": "bmunits.json",
    "elexon_b1610": "b1610.json",
    "neso_dno_areas": "dno_areas.geojson",
    "osm_gb_power": "plants.json",
    "wikidata": "images.json",
}


def fetch(source: Source, raw: Path = RAW, force: bool = False) -> Fetched:
    if source.is_blocked:
        raise RuntimeError(
            f"{source.id}: refusing to fetch a source with an unresolved licence. "
            f"{' '.join((source.blocking_issue or '').split())}"
        )
    if source.is_vendored:
        path = find_vendored(source, raw)
        return Fetched(source.id, path, sha256(path), from_cache=True)

    if (name := QUERY_SOURCES.get(source.id)) is not None:
        dest = raw / source.id / name
        if dest.exists() and not force:
            return Fetched(source.id, dest, sha256(dest), from_cache=True)
        raise MissingVendoredInput(
            f"\n  {source.name} has not been fetched yet.\n"
            f"  Expected at : data/raw/{source.id}/{name}\n"
            f"  Run         : make fetch-gb\n"
        )

    if not source.download_url:
        raise RuntimeError(f"{source.id}: access is {source.access!r} but no download_url set")

    dest_dir = raw / source.id
    if source.files:
        # Multi-file source (gridfinder): base URL + named files.
        paths = []
        for name in source.files:
            dest = dest_dir / name
            if force or not dest.exists():
                _download(source.download_url.rstrip("/") + "/" + name, dest)
            paths.append(dest)
        primary = paths[0]
    else:
        primary = dest_dir / Path(source.download_url).name
        cached = primary.exists() and not force
        if not cached:
            _download(source.download_url, primary)
        return Fetched(source.id, primary, sha256(primary), from_cache=cached)

    return Fetched(source.id, primary, sha256(primary), from_cache=False)


def plan(reg: Registry | None = None) -> dict[str, list[Source]]:
    """What a full fetch would do, without doing it. Used by `make fetch --dry-run`."""
    reg = reg or load()
    inputs = [s for s in reg.sources.values() if s.role in ("input", "validation")]
    return {
        "automatic": [s for s in inputs if s.access == "direct" and not s.is_blocked],
        "vendored": [s for s in inputs if s.is_vendored],
        "authored": [s for s in inputs if s.access == "derived"],
        "blocked": [s for s in inputs if s.is_blocked],
    }


if __name__ == "__main__":
    import sys

    groups = plan()
    for label, srcs in groups.items():
        if not srcs:
            continue
        print(f"\n{label.upper()} ({len(srcs)})")
        for s in sorted(srcs, key=lambda x: x.id):
            note = ""
            if label == "vendored":
                note = f"  <- data/raw/{s.raw_glob}"
            elif label == "blocked":
                note = f"  <- {s.licence}"
            print(f"  {s.id:28} {s.name}{note}")
    if groups["blocked"]:
        print(f"\n{len(groups['blocked'])} source(s) blocked on licence resolution.")
        sys.exit(0)
