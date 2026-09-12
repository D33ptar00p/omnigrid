import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

import { FUEL_COLOR, FUEL_LABEL, FUEL_ORDER, FOSSIL, fuelColorExpression, type Fuel } from "./lib/palette";
import { power } from "./lib/format";
import { Sources, type Manifest } from "./lib/provenance";
import * as gbView from "./gb/view";
import * as detail from "./panels/detail";
import * as gbPanel from "./panels/gb";
import * as about from "./panels/about";

const SRC = "assets";
const LAYER = "assets-circles";

type View = "global" | "gb";
let view: View = "global";
const GB_CENTRE: [number, number] = [-2.6, 54.3];


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

  await gbView.add(map);
  gbView.setVisible(map, false);
  wireInteraction(sources);
  wireGb(sources);
  wireViewToggle();
}

function wireViewToggle(): void {
  const bar = document.getElementById("views") as HTMLElement;
  bar.hidden = false;
  bar.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button");
    if (!btn) return;
    setView(btn.dataset.view as View);
  });
  setView("global");
}

function setView(next: View): void {
  view = next;
  detail.hide();
  gbPanel.hide();

  const global = next === "global";
  for (const id of [LAYER]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", global ? "visible" : "none");
  }
  gbView.setVisible(map, !global);

  document.querySelectorAll("#views button").forEach((b) => {
    b.classList.toggle("on", (b as HTMLElement).dataset.view === next);
  });
  document.getElementById("legend")!.hidden = false;
  (document.getElementById("legend-gb") as HTMLElement).hidden = global;
  (document.getElementById("view-note") as HTMLElement).textContent = global
    ? "Every power source on Earth, from open data."
    : "Great Britain: metered output on the real distribution network.";

  if (!global) map.flyTo({ center: GB_CENTRE, zoom: 5.1, duration: 900 });
}

/** GB interactions: plants and the real distribution regions. */
function wireGb(sources: Sources): void {
  let hovered: string | number | undefined;

  map.on("mousemove", gbView.REGION_FILL, (e) => {
    const f = e.features?.[0];
    if (!f) return;
    if (hovered !== undefined) {
      map.setFeatureState({ source: gbView.REGION_SRC, id: hovered }, { hover: false });
    }
    hovered = f.id;
    if (hovered !== undefined) {
      map.setFeatureState({ source: gbView.REGION_SRC, id: hovered }, { hover: true });
    }
  });
  map.on("mouseleave", gbView.REGION_FILL, () => {
    if (hovered !== undefined) {
      map.setFeatureState({ source: gbView.REGION_SRC, id: hovered }, { hover: false });
    }
    hovered = undefined;
  });

  map.on("click", gbView.PLANT_LAYER, (e) => {
    const f = e.features?.[0];
    if (!f) return;
    e.preventDefault();
    gbPanel.showPlant(revive(f.properties as Record<string, unknown>), sources);
  });

  map.on("click", gbView.REGION_FILL, (e) => {
    // A plant click wins: the smaller target is the more specific intent.
    if (map.queryRenderedFeatures(e.point, { layers: [gbView.PLANT_LAYER] }).length) return;
    const f = e.features?.[0];
    if (f) gbPanel.showRegion(revive(f.properties as Record<string, unknown>) as never, sources);
  });

  map.on("mousemove", gbView.PLANT_LAYER, (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const p = f.properties as Record<string, unknown>;
    const fuel = (p._fuel ?? "other") as Fuel;
    const tooltip = document.getElementById("tooltip") as HTMLElement;
    tooltip.innerHTML = `<div class="t-name">${p.name}</div>
      <div class="t-meta"><span style="color:${FUEL_COLOR[fuel]}">${FUEL_LABEL[fuel]}</span>
      ${Number(p._mw) > 0 ? ` · ${power(Number(p._mw))}` : ""}</div>`;
    tooltip.style.left = `${e.point.x}px`;
    tooltip.style.top = `${e.point.y}px`;
    tooltip.hidden = false;
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", gbView.PLANT_LAYER, () => {
    (document.getElementById("tooltip") as HTMLElement).hidden = true;
    map.getCanvas().style.cursor = "";
  });
}

/** GeoJSON nests objects as JSON strings once they cross into MapLibre. */
function revive(raw: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    out[k] = typeof v === "string" && (v.startsWith("{") || v.startsWith("["))
      ? safeParse(v) : v;
  }
  return out;
}

function wireInteraction(sources: Sources) {
  const tooltip = document.getElementById("tooltip") as HTMLElement;

  map.on("mousemove", LAYER, (e) => {
    if (view !== "global") return;
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
    if (view !== "global") return;
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
    const layers = [LAYER, gbView.PLANT_LAYER, gbView.REGION_FILL]
      .filter((l) => map.getLayer(l));
    if (!map.queryRenderedFeatures(e.point, { layers }).length) {
      detail.hide();
      gbPanel.hide();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      detail.hide();
    }
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
  const warnings = manifest.warnings;
  if (!warnings.length) return;
  const b = document.getElementById("banner") as HTMLElement;

  // Every caveat stays reachable, but stacking eleven of them over the map made
  // the map unusable and the caveats unread. Lead with the one that changes what
  // you are looking at; keep the rest one click away.
  const [lead, ...rest] = warnings;
  const fmt = (w: string) => {
    const i = w.indexOf(":");
    return i > 0 && i < 40
      ? `<strong>${w.slice(0, i)}</strong>${w.slice(i)}`
      : w;
  };

  b.innerHTML = `
    <div class="banner-lead">${fmt(lead!)}</div>
    ${rest.length ? `
      <button class="banner-more" type="button">
        ${rest.length} more caveat${rest.length === 1 ? "" : "s"} about this build
      </button>
      <ul class="banner-rest" hidden>${rest.map((w) => `<li>${fmt(w)}</li>`).join("")}</ul>
    ` : ""}`;
  b.hidden = false;

  const more = b.querySelector(".banner-more");
  const list = b.querySelector(".banner-rest") as HTMLElement | null;
  more?.addEventListener("click", () => {
    if (!list) return;
    list.hidden = !list.hidden;
    more.textContent = list.hidden
      ? `${rest.length} more caveats about this build`
      : "Hide caveats";
  });
}

map.on("load", () => {
  boot().catch((err) => {
    console.error(err);
    document.getElementById("brand")!.insertAdjacentHTML(
      "beforeend",
      `<p style="color:#e08a8a">Failed to load data: ${err}</p>`);
  });
});
