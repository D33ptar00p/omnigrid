"""Trace the physical grid: which wires connect to a power station, and how far.

This is surveyed infrastructure, not a model. OpenStreetMap contributors have
mapped GB's power lines with their voltages; two lines that share a vertex are
physically joined. Following those joins outward from a plant answers a question
that *does* have a factual answer: what is this station wired to?

What it is not: a claim about where the electricity goes. The GB transmission
network is a single connected graph, so tracing far enough from any plant
reaches almost all of it. That is exactly why a per-plant catchment area does not
exist -- and showing the trace by hop distance makes the point visible rather
than asserting it.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SOURCE_ID = "osm_gb_power"

#: Endpoints within this distance are treated as the same electrical node.
#: OSM ways that meet at a substation often differ in the last decimal place.
SNAP_DEGREES = 1e-5  # ~1 m

#: Transmission in GB. Below this is distribution: far more numerous, and not
#: what "reach from a power station" is usually asking about.
TRANSMISSION_VOLTS = 132_000

#: A plant connects to any line whose vertex falls within this radius. Plants are
#: mapped as areas and their switchyard is usually inside the polygon, so this is
#: generous enough to catch the connection without inventing one.
CONNECT_KM = 2.0


def _max_voltage(raw: str | None) -> int | None:
    """OSM records multi-circuit towers as "400000;275000". The highest wins."""
    if not raw:
        return None
    best = None
    for part in str(raw).replace(",", ";").split(";"):
        try:
            v = int(float(part.strip()))
        except (TypeError, ValueError):
            continue
        best = v if best is None else max(best, v)
    return best


@dataclass
class Line:
    id: int
    voltage: int | None
    name: str | None
    geometry: list[tuple[float, float]]  # (lon, lat)

    @property
    def is_transmission(self) -> bool:
        return self.voltage is not None and self.voltage >= TRANSMISSION_VOLTS


@dataclass
class GridGraph:
    """Lines plus the adjacency implied by shared vertices."""

    lines: list[Line] = field(default_factory=list)
    #: line index -> indices of lines sharing at least one vertex
    adjacency: dict[int, set[int]] = field(default_factory=lambda: defaultdict(set))
    #: snapped node key -> line indices touching it
    nodes: dict[tuple[int, int], set[int]] = field(default_factory=lambda: defaultdict(set))
    #: how many substations actually joined two or more lines
    substation_joins: int = 0

    def component_of(self, start: int) -> set[int]:
        seen = {start}
        queue = deque([start])
        while queue:
            for nxt in self.adjacency.get(queue.popleft(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    def hops_from(self, starts: Iterable[int], max_hops: int) -> dict[int, int]:
        """Breadth-first hop distance in lines, capped.

        The cap is the point: uncapped, the answer for any GB plant is "almost
        the whole network", which is true but says nothing.
        """
        dist: dict[int, int] = {s: 0 for s in starts}
        queue = deque(dist)
        while queue:
            cur = queue.popleft()
            if dist[cur] >= max_hops:
                continue
            for nxt in self.adjacency.get(cur, ()):
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        return dist


def _key(lon: float, lat: float) -> tuple[int, int]:
    return (round(lon / SNAP_DEGREES), round(lat / SNAP_DEGREES))


def load_substations(path: Path):
    """Substation footprints and points: the electrical junctions of the grid.

    Lines often do share a vertex with the next line in the same run, so
    endpoint snapping alone produces plenty of adjacency -- but it leaves the
    network in disconnected fragments, because separate runs meet at a
    substation rather than at each other. Adding substations as junctions is
    what makes it one grid: Drax's connected component goes from a single line
    to the great majority of GB transmission.
    """
    from shapely.geometry import Point, Polygon

    data = json.loads(path.read_text())
    shapes = []
    for el in data.get("elements", []):
        if geom := el.get("geometry"):
            ring = [(p["lon"], p["lat"]) for p in geom]
            if len(ring) >= 4:
                try:
                    shapes.append(Polygon(ring).buffer(0))
                    continue
                except Exception:
                    pass
        if (lon := el.get("lon")) is not None and (lat := el.get("lat")) is not None:
            shapes.append(Point(lon, lat))
    return [g for g in shapes if not g.is_empty]


def build_graph(path: Path, *, substations: Path | None = None,
                transmission_only: bool = True,
                junction_radius_deg: float = 0.0025) -> GridGraph:
    """Read an Overpass dump of power=line/cable and wire it into a graph.

    Lines are joined two ways: a shared endpoint (rare), and termination at the
    same substation (the usual case). `junction_radius_deg` is roughly 250 m, to
    allow for an endpoint drawn just outside the substation fence.
    """
    data = json.loads(path.read_text())
    graph = GridGraph()

    for el in data.get("elements", []):
        geometry = el.get("geometry")
        if not geometry or len(geometry) < 2:
            continue
        tags = el.get("tags", {})
        voltage = _max_voltage(tags.get("voltage"))
        line = Line(
            id=el["id"],
            voltage=voltage,
            name=tags.get("name") or tags.get("ref"),
            geometry=[(round(p["lon"], 6), round(p["lat"], 6)) for p in geometry],
        )
        if transmission_only and not line.is_transmission:
            continue
        idx = len(graph.lines)
        graph.lines.append(line)
        # Only endpoints join lines electrically; mid-span crossings do not.
        for lon, lat in (line.geometry[0], line.geometry[-1]):
            graph.nodes[_key(lon, lat)].add(idx)

    for touching in graph.nodes.values():
        if len(touching) < 2:
            continue
        for a in touching:
            graph.adjacency[a] |= touching - {a}

    if substations is not None:
        _join_at_substations(graph, substations, junction_radius_deg)
    return graph


def _join_at_substations(graph: GridGraph, path: Path, radius_deg: float) -> None:
    from shapely import STRtree
    from shapely.geometry import Point

    shapes = load_substations(path)
    if not shapes:
        return
    tree = STRtree(shapes)

    at_substation: dict[int, set[int]] = defaultdict(set)
    for idx, line in enumerate(graph.lines):
        for lon, lat in (line.geometry[0], line.geometry[-1]):
            point = Point(lon, lat)
            for sub in tree.query(point.buffer(radius_deg)):
                if shapes[sub].distance(point) <= radius_deg:
                    at_substation[int(sub)].add(idx)

    for touching in at_substation.values():
        if len(touching) < 2:
            continue
        for a in touching:
            graph.adjacency[a] |= touching - {a}
    graph.substation_joins = sum(
        1 for v in at_substation.values() if len(v) > 1)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def connections_for(graph: GridGraph, lon: float, lat: float,
                    radius_km: float = CONNECT_KM) -> list[int]:
    """Lines with a vertex near a point: the plant's physical connections.

    Returns an empty list when nothing is close, which is the honest answer for
    a plant OSM has not wired up -- most small embedded generators.
    """
    hits: list[tuple[float, int]] = []
    for idx, line in enumerate(graph.lines):
        best = min(
            (_haversine_km(lon, lat, plon, plat) for plon, plat in line.geometry),
            default=float("inf"),
        )
        if best <= radius_km:
            hits.append((best, idx))
    hits.sort()
    return [idx for _, idx in hits]


def connections_bulk(graph: GridGraph, points: list[tuple[float, float]],
                     radius_km: float = CONNECT_KM) -> list[list[int]]:
    """`connections_for` over many points, via a spatial index.

    The linear scan is fine for one plant and hopeless for several thousand.
    """
    from shapely import STRtree
    from shapely.geometry import LineString, Point

    geoms = [LineString(line.geometry) for line in graph.lines]
    tree = STRtree(geoms)
    # Degrees are not kilometres, but at GB latitudes a degree of longitude is
    # ~65 km and of latitude ~111 km; the smaller is the safe conversion for a
    # search radius that must not miss anything.
    radius_deg = radius_km / 65.0

    out: list[list[int]] = []
    for lon, lat in points:
        point = Point(lon, lat)
        hits: list[tuple[float, int]] = []
        for idx in tree.query(point.buffer(radius_deg)):
            line = graph.lines[int(idx)]
            best = min(_haversine_km(lon, lat, plon, plat)
                       for plon, plat in line.geometry)
            if best <= radius_km:
                hits.append((best, int(idx)))
        hits.sort()
        out.append([i for _, i in hits])
    return out


def to_geojson(graph: GridGraph) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": i,
                "geometry": {"type": "LineString", "coordinates": line.geometry},
                "properties": {
                    "i": i,
                    "osm_id": line.id,
                    "voltage": line.voltage,
                    "name": line.name,
                },
            }
            for i, line in enumerate(graph.lines)
        ],
    }


def adjacency_json(graph: GridGraph) -> dict[str, list[int]]:
    """Adjacency in a form the browser can breadth-first search directly."""
    return {str(k): sorted(v) for k, v in graph.adjacency.items() if v}
