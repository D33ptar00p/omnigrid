import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

import { FUEL_COLOR, FUEL_LABEL, FUEL_ORDER, FOSSIL, fuelColorExpression, type Fuel } from "./lib/palette";
import { power } from "./lib/format";
import { Sources, type Manifest } from "./lib/provenance";
import * as detail from "./panels/detail";
import * as about from "./panels/about";

const SRC = "assets";
const LAYER = "assets-circles";

const map = new maplibregl.Map({
  container: "map",
  // OSM-derived dark vector basemap, no API key. Production swaps this for a
  // self-hosted Protomaps PMTiles archive (see the plan) -- same data, one file.
  style: "https://tiles.openfreemap.org/styles/dark",
  center: [8, 30],
  zoom: 1.7,
  maxZoom: 16,
  attributionControl: { compact: true },
});

// Exposed for end-to-end tests, which need to resolve a feature to a pixel.
if (import.meta.env.DEV) (window as unknown as { __map: maplibregl.Map }).__map = map;

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

const hidden = new Set<Fuel>();

async function boot() {
  const manifest: Manifest = await fetch("/data/manifest.json").then((r) => r.json());
  const sources = new Sources(manifest);

  about.init(sources);
  renderLegend();
  renderBanner(manifest);

  map.addSource(SRC, { type: "geojson", data: "/data/assets.geojson" });

  map.addLayer({
    id: LAYER,
    type: "circle",
    source: SRC,
    paint: {
      // Radius by capacity, on a sqrt-ish ramp so area tracks magnitude rather
      // than radius -- a 4 GW plant should not read as 100x a 40 MW one.
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        2, ["interpolate", ["linear"], ["sqrt", ["max", ["get", "_mw"], 1]], 1, 1.2, 80, 7],
        6, ["interpolate", ["linear"], ["sqrt", ["max", ["get", "_mw"], 1]], 1, 2.5, 80, 18],
        12, ["interpolate", ["linear"], ["sqrt", ["max", ["get", "_mw"], 1]], 1, 5, 80, 46],
      ],
      "circle-color": fuelColorExpression(),
      "circle-opacity": 0.78,
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 3, 0, 6, 0.6],
      "circle-stroke-color": "#0b0e14",
      "circle-stroke-opacity": 0.5,
    },
  });

  wireInteraction(sources);
}

function wireInteraction(sources: Sources) {
  const tooltip = document.getElementById("tooltip") as HTMLElement;

  map.on("mousemove", LAYER, (e) => {
    const f = e.features?.[0];
    if (!f) return;
    map.getCanvas().style.cursor = "pointer";
    const p = f.properties as Record<string, any>;
    const fuel = (p._fuel ?? "other") as Fuel;
    tooltip.innerHTML = `
      <div class="t-name">${p.name}</div>
      <div class="t-meta">
        <span style="color:${FUEL_COLOR[fuel]}">${FUEL_LABEL[fuel]}</span>
        · ${power(Number(p._mw))} · ${p.country}
      </div>`;
    tooltip.style.left = `${e.point.x}px`;
    tooltip.style.top = `${e.point.y}px`;
    tooltip.hidden = false;
  });

  map.on("mouseleave", LAYER, () => {
    map.getCanvas().style.cursor = "";
    tooltip.hidden = true;
  });

  map.on("click", LAYER, (e) => {
    const f = e.features?.[0];
    if (!f) return;
    // GeoJSON properties arrive JSON-encoded when nested; revive them.
    const raw = f.properties as Record<string, any>;
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(raw)) {
      props[k] = typeof v === "string" && v.startsWith("{") ? safeParse(v) : v;
    }
    detail.show(props, sources);
  });

  map.on("click", (e) => {
    if (!map.queryRenderedFeatures(e.point, { layers: [LAYER] }).length) detail.hide();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") detail.hide();
  });
}

function safeParse(s: string): unknown {
  try { return JSON.parse(s); } catch { return s; }
}

function renderLegend() {
  const ul = document.getElementById("legend-items") as HTMLElement;
  ul.innerHTML = FUEL_ORDER.map((f, i) => {
    // A rule between the fossil block and the rest, so the split is visible.
    const rule = i > 0 && FOSSIL.has(FUEL_ORDER[i - 1]!) && !FOSSIL.has(f)
      ? '<hr class="fossil-rule">' : "";
    return `${rule}<li data-fuel="${f}">
      <span class="swatch" style="background:${FUEL_COLOR[f]}"></span>${FUEL_LABEL[f]}
    </li>`;
  }).join("");

  ul.addEventListener("click", (e) => {
    const li = (e.target as HTMLElement).closest("li");
    if (!li) return;
    const fuel = li.dataset.fuel as Fuel;
    hidden.has(fuel) ? hidden.delete(fuel) : hidden.add(fuel);
    li.classList.toggle("off", hidden.has(fuel));
    applyFilter();
  });
}

function applyFilter() {
  if (!map.getLayer(LAYER)) return;
  map.setFilter(LAYER, hidden.size
    ? ["!", ["in", ["get", "_fuel"], ["literal", [...hidden]]]]
    : null);
}

/** A degraded build must say so on the map, not only in the logs. */
function renderBanner(manifest: Manifest) {
  if (!manifest.warnings.length) return;
  const b = document.getElementById("banner") as HTMLElement;
  b.innerHTML = manifest.warnings
    .map((w) => {
      const [head, ...rest] = w.split(":");
      return `<strong>${head}</strong>${rest.length ? ":" + rest.join(":") : ""}`;
    })
    .join("<br>");
  b.hidden = false;
}

map.on("load", () => {
  boot().catch((err) => {
    console.error(err);
    document.getElementById("brand")!.insertAdjacentHTML(
      "beforeend",
      `<p style="color:#e08a8a">Failed to load data: ${err}</p>`);
  });
});
