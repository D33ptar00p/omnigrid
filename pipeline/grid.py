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

#: A plant connects to a line that *terminates* within this radius. Tighter than
#: the old any-vertex rule because an endpoint is a real electrical termination,
#: not a circuit that happens to cross the site.
CONNECT_KM = 1.0


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
    """Lines that *terminate* near each point: its grid connections.

    Matching any vertex within the radius was wrong. It counted every line that
    merely passes overhead, which produced physically impossible results — a
    2.3 MW sewage works reading as connected at 400 kV because a supergrid
    circuit crosses the site. A connection terminates at a plant; a line passing
    over it does not, so only endpoints count.

    With that fixed, connection voltage becomes a real signal rather than noise:
    the median rises monotonically from 132 kV for sub-10 MW plants to 400 kV
    above 1 GW, which is how the grid is actually built.
    """
    from shapely import STRtree
    from shapely.geometry import Point

    endpoints = []
    owner: list[int] = []
    for idx, line in enumerate(graph.lines):
        for lon, lat in (line.geometry[0], line.geometry[-1]):
            endpoints.append(Point(lon, lat))
            owner.append(idx)
    if not endpoints:
        return [[] for _ in points]
    tree = STRtree(endpoints)

    # Degrees are not kilometres, but at GB latitudes a degree of longitude is
    # ~65 km and of latitude ~111 km; the smaller is the safe conversion for a
    # search radius that must not miss anything.
    radius_deg = radius_km / 65.0

    out: list[list[int]] = []
    for lon, lat in points:
        hits: list[tuple[float, int]] = []
        for j in tree.query(Point(lon, lat).buffer(radius_deg)):
            j = int(j)
            d = _haversine_km(lon, lat, endpoints[j].x, endpoints[j].y)
            if d <= radius_km:
                hits.append((d, owner[j]))
        hits.sort()
        seen: set[int] = set()
        nearest: list[int] = []
        for _, idx in hits:
            if idx not in seen:
                seen.add(idx)
                nearest.append(idx)
        out.append(nearest)
    return out


def reach_for(graph: GridGraph, roots: list[int]) -> dict[str, Any]:
    """What a plant is wired to: its connection, and how far that network goes.

    The share is deliberately a *number* rather than something drawn. It is ~92%
    for almost every connected plant in GB, so rendering it paints an identical
    picture for a 5 MW solar farm and for Drax — the same answer to every
    question, which is no answer at all. Said as a figure it still makes the
    point, and the map is freed to show the connection, which genuinely differs.
    """
    if not roots:
        return {"lines": 0, "voltage": None, "component": 0, "share": 0.0}
    volts = [graph.lines[i].voltage for i in roots if graph.lines[i].voltage]
    component = len(graph.component_of(roots[0]))
    return {
        "lines": len(roots),
        "voltage": max(volts) if volts else None,
        "component": component,
        "share": round(component / len(graph.lines), 4) if graph.lines else 0.0,
    }


def subset_geojson(graph: GridGraph, keep: set[int]) -> dict[str, Any]:
    """Geometry for a chosen subset of lines, renumbered to a dense index.

    The full all-voltage network is 24 MB of geometry. Connections and reach are
    computed across all of it, but only the lines actually drawn are shipped:
    transmission, plus every line that is some plant's connection.
    """
    order = sorted(keep)
    remap = {old: new for new, old in enumerate(order)}
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": remap[old],
                "geometry": {"type": "LineString", "coordinates": graph.lines[old].geometry},
                "properties": {
                    "i": remap[old],
                    "osm_id": graph.lines[old].id,
                    "voltage": graph.lines[old].voltage,
                    "name": graph.lines[old].name,
                },
            }
            for old in order
        ],
    }, remap


def subset_adjacency(graph: GridGraph, remap: dict[int, int]) -> dict[str, list[int]]:
    """Adjacency restricted to the shipped lines, renumbered to match."""
    out: dict[str, list[int]] = {}
    for old, neighbours in graph.adjacency.items():
        if old not in remap:
            continue
        near = sorted(remap[n] for n in neighbours if n in remap)
        if near:
            out[str(remap[old])] = near
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
