/**
 * The Great Britain view: measured generation on the real distribution network.
 *
 * Two layers answer two different questions, and the distinction is the whole
 * point of this view:
 *
 *   regions  — the 14 real DNO licence areas, shaded by the embedded generation
 *              Elexon publishes as feeding them. A published fact.
 *   plants   — every power station OpenStreetMap has surveyed, at its real
 *              location. Metered output is attached where the station could be
 *              matched to an Elexon BM Unit.
 *
 * Nothing here is modelled. A transmission-connected station has no region
 * shaded for it, because it feeds the national grid rather than any one area.
 */

import type maplibregl from "maplibre-gl";
import { FUEL_COLOR, type Fuel } from "../lib/palette";

export const REGION_SRC = "gb-regions";
export const REGION_FILL = "gb-region-fill";
export const REGION_LINE = "gb-region-line";
export const PLANT_SRC = "gb-plants";
export const PLANT_LAYER = "gb-plants-circles";
export const LINE_SRC = "gb-lines";
export const LINE_LAYER = "gb-lines";
export const TRACE_LAYER = "gb-lines-trace";

export interface RegionProps {
  code: string;
  area: string;
  dno: string;
  dno_full: string;
  embedded_units: number;
  embedded_capacity_mw: number;
  fuel_mix_mw: Record<string, number>;
  fuel_undeclared_mw: number;
  metered_mwh: number;
  dominant_fuel: string | null;
}

/**
 * Regions are shaded by embedded capacity, not by fuel.
 *
 * Elexon declares no fuel type for 25 of the 31 GW of embedded capacity, so a
 * fuel colouring would present a third of the data as though it were all of it.
 * Capacity is complete, so capacity is what the colour carries; the mix, with
 * its undeclared share stated, lives in the panel where it can be qualified.
 */
function capacityFillExpression(): unknown[] {
  return [
    "interpolate", ["linear"], ["get", "embedded_capacity_mw"],
    0, "#16202e",
    1000, "#1d3446",
    2000, "#245061",
    3000, "#2c6b78",
    4500, "#3f9a97",
  ];
}

export async function add(map: maplibregl.Map): Promise<void> {
  map.addSource(REGION_SRC, {
    type: "geojson",
    data: "/data/gb/regions.geojson",
    // Feature-state hover needs stable ids, and the source has none of its own.
    generateId: true,
  });
  map.addSource(PLANT_SRC, { type: "geojson", data: "/data/gb/plants.geojson" });

  // Regions get a real outline — unlike a modelled shed, these boundaries are
  // published and genuinely have edges.
  map.addLayer({
    id: REGION_FILL,
    type: "fill",
    source: REGION_SRC,
    paint: {
      "fill-color": capacityFillExpression() as never,
      "fill-opacity": [
        "case", ["boolean", ["feature-state", "hover"], false], 0.72, 0.45,
      ],
    },
  });
  map.addLayer({
    id: REGION_LINE,
    type: "line",
    source: REGION_SRC,
    paint: {
      "line-color": "#7d8ea6",
      "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2, 0.9],
      "line-opacity": 0.65,
    },
  });

  // The surveyed transmission network, under the plants. Dim by default: it is
  // context until you ask a question of it.
  map.addSource(LINE_SRC, { type: "geojson", data: "/data/gb/lines.geojson" });
  map.addLayer({
    id: LINE_LAYER,
    type: "line",
    source: LINE_SRC,
    paint: {
      "line-color": [
        "step", ["coalesce", ["get", "voltage"], 0],
        "#3d4c60", 275000, "#4e6079", 400000, "#5f7694",
      ],
      "line-width": [
        "interpolate", ["linear"], ["zoom"],
        5, ["case", [">=", ["coalesce", ["get", "voltage"], 0], 400000], 0.7, 0.4],
        10, ["case", [">=", ["coalesce", ["get", "voltage"], 0], 400000], 2.2, 1.2],
      ],
      "line-opacity": 0.5,
    },
  });

  // The traced subset, drawn on top and coloured by how many hops out it is.
  map.addLayer({
    id: TRACE_LAYER,
    type: "line",
    source: LINE_SRC,
    filter: ["in", ["get", "i"], ["literal", []]],
    paint: {
      "line-color": [
        "interpolate", ["linear"], ["coalesce", ["feature-state", "hop"], 0],
        0, "#ffe07a", 2, "#8fe3c8", 5, "#56a8c6", 9, "#3f6f9e",
      ],
      "line-width": [
        "interpolate", ["linear"], ["zoom"],
        5, ["interpolate", ["linear"], ["coalesce", ["feature-state", "hop"], 0], 0, 2.4, 10, 0.8],
        10, ["interpolate", ["linear"], ["coalesce", ["feature-state", "hop"], 0], 0, 6, 10, 2],
      ],
      "line-opacity": 0.95,
      "line-blur": 0.3,
    },
  });

  map.addLayer({
    id: PLANT_LAYER,
    type: "circle",
    source: PLANT_SRC,
    paint: {
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        5, ["interpolate", ["linear"], ["sqrt", ["max", ["get", "_mw"], 1]], 1, 1.6, 45, 9],
        9, ["interpolate", ["linear"], ["sqrt", ["max", ["get", "_mw"], 1]], 1, 3, 45, 22],
        13, ["interpolate", ["linear"], ["sqrt", ["max", ["get", "_mw"], 1]], 1, 6, 45, 48],
      ],
      "circle-color": [
        "match", ["get", "_fuel"],
        ...Object.entries(FUEL_COLOR).flatMap(([f, c]) => [f, c]),
        FUEL_COLOR.other,
      ] as never,
      // Plants outside every GB DNO area -- Northern Ireland, Isle of Man,
      // Channel Islands -- are on other systems entirely. Shown, because they
      // are real, but dimmed so they do not read as part of the GB grid.
      "circle-opacity": ["case", ["get", "off_gb_network"], 0.28, 0.85],
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 6, 0, 9, 0.7],
      "circle-stroke-color": "#0b0e14",
      "circle-stroke-opacity": 0.6,
    },
  });
}

/**
 * Restrict the GB plant layer to one operator.
 *
 * The operator comes from OpenStreetMap's `operator` tag, which names the site
 * operator. Elexon's lead party -- who trades the output -- is often a different
 * company, so the two lists barely overlap and this filter is deliberately the
 * OSM one: it is the operator of the physical station shown on the map.
 */
export function filterByOperator(map: maplibregl.Map, operator: string | null): void {
  if (!map.getLayer(PLANT_LAYER)) return;
  map.setFilter(PLANT_LAYER, operator ? ["==", ["get", "_operator"], operator] : null);
}

/** Operators present in the data, with their plant counts, most plants first. */
export function operatorCounts(map: maplibregl.Map): [string, number][] {
  const counts = new Map<string, number>();
  for (const f of map.querySourceFeatures(PLANT_SRC)) {
    const op = (f.properties?._operator ?? "") as string;
    if (op) counts.set(op, (counts.get(op) ?? 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** Highlight a traced set of lines, coloured by hop distance. */
export function showTrace(map: maplibregl.Map, hops: Map<number, number> | null): void {
  if (!map.getLayer(TRACE_LAYER)) return;
  if (!hops || hops.size === 0) {
    map.setFilter(TRACE_LAYER, ["in", ["get", "i"], ["literal", []]]);
    return;
  }
  const ids = [...hops.keys()];
  map.setFilter(TRACE_LAYER, ["in", ["get", "i"], ["literal", ids]]);
  for (const [id, hop] of hops) {
    map.setFeatureState({ source: LINE_SRC, id }, { hop });
  }
}

export function setVisible(map: maplibregl.Map, visible: boolean): void {
  const v = visible ? "visible" : "none";
  for (const id of [REGION_FILL, REGION_LINE, LINE_LAYER, TRACE_LAYER, PLANT_LAYER]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }
}

/** Regions ranked by capacity, for the region breakdown. */
export function fuelBreakdown(props: RegionProps): [Fuel, number][] {
  const mix = typeof props.fuel_mix_mw === "string"
    ? (JSON.parse(props.fuel_mix_mw) as Record<string, number>)
    : props.fuel_mix_mw;
  return Object.entries(mix ?? {})
    .sort((a, b) => b[1] - a[1]) as [Fuel, number][];
}
