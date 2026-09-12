"""Pack the global asset set into something a browser can actually load.

145,396 plants as GeoJSON is 100 MB, most of it the same 70 bytes of
`{"type":"Feature","geometry":{"type":"Point",...}}` scaffolding repeated for
every point. Vector tiles would be the usual answer, but tippecanoe is not
available here, and it turns out not to be needed: storing the fields
column-wise instead of row-wise removes the scaffolding entirely and gets the
whole planet under 10 MB, which gzip takes to about 3.

The client reassembles GeoJSON once on load. That costs a fraction of a second
and saves ninety megabytes of transfer.

Detail beyond what the map draws — owner, commissioning year, provenance for
every field — lives in a separate blob addressed by HTTP Range, so clicking a
plant costs only that plant's bytes.
"""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.schema import Asset, Fuel

#: Fuel is sent as an index into this list rather than a repeated string.
FUEL_ORDER = [f.value for f in Fuel]
_FUEL_INDEX = {f: i for i, f in enumerate(FUEL_ORDER)}

#: ~11 m. Finer than any of these sources actually resolves.
COORD_DP = 4


@dataclass
class PackedAssets:
    count: int = 0
    bytes_points: int = 0
    bytes_detail: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def total_mb(self) -> float:
        return (self.bytes_points + self.bytes_detail) / 1e6


def write(assets: list[Asset], dist: Path) -> PackedAssets:
    dist.mkdir(parents=True, exist_ok=True)
    stats = PackedAssets(count=len(assets))

    lon: list[float] = []
    lat: list[float] = []
    fuel: list[int] = []
    mw: list[float] = []
    names: list[str] = []
    status: list[int] = []

    statuses: list[str] = []
    status_index: dict[str, int] = {}

    detail_index: list[list[int]] = []
    offset = 0
    detail_parts: list[bytes] = []

    for a in assets:
        lon.append(round(a.lon, COORD_DP))
        lat.append(round(a.lat, COORD_DP))
        fuel.append(_FUEL_INDEX[a.fuel.value.value])
        mw.append(round(a.capacity_mw.value, 1) if a.capacity_mw else 0.0)
        names.append(a.name)

        key = a.status.value.value
        if key not in status_index:
            status_index[key] = len(statuses)
            statuses.append(key)
        status.append(status_index[key])

        # Full record, with provenance, fetched only when a plant is clicked.
        blob = gzip.compress(json.dumps(a.to_json(), separators=(",", ":")).encode())
        detail_parts.append(blob)
        detail_index.append([offset, len(blob)])
        offset += len(blob)

    points = {
        "count": len(assets),
        "fuels": FUEL_ORDER,
        "statuses": statuses,
        "lon": lon, "lat": lat, "fuel": fuel, "mw": mw,
        "status": status, "name": names,
    }
    points_path = dist / "assets.points.json"
    points_path.write_text(json.dumps(points, separators=(",", ":")))
    stats.bytes_points = points_path.stat().st_size

    (dist / "assets.detail.bin").write_bytes(b"".join(detail_parts))
    (dist / "assets.detail.idx.json").write_text(
        json.dumps(detail_index, separators=(",", ":")))
    stats.bytes_detail = (dist / "assets.detail.bin").stat().st_size

    stats.notes.append(
        f"{len(assets):,} plants packed column-wise: "
        f"{stats.bytes_points/1e6:.1f} MB of render data plus "
        f"{stats.bytes_detail/1e6:.1f} MB of detail fetched on demand."
    )
    return stats
