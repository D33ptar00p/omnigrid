/** The detail panel. Every value shows its source inline. */

import { FUEL_COLOR, FUEL_LABEL, type Fuel } from "../lib/palette";
import { energy, power } from "../lib/format";
import { KIND_TITLE, isCited, type Cited, type Sources } from "../lib/provenance";

const el = document.getElementById("panel") as HTMLElement;

/** One labelled value plus its citation. */
function field(label: string, cited: Cited | undefined, render: (v: never) => string,
               sources: Sources): string {
  if (!cited) return "";
  const src = sources.get(cited.s);
  const value = render(cited.v as never);
  const link = src
    ? `<a href="${src.url}" target="_blank" rel="noopener">${sources.short(cited.s)}</a>`
    : cited.s;
  const method = cited.m ? `<span title="method">· ${cited.m}</span>` : "";
  return `
    <div class="field">
      <div class="field-label">${label}</div>
      <div class="field-value ${cited.k === "modelled" ? "is-modelled" : ""}">${value}</div>
      <div class="cite">
        <span class="kind ${cited.k}" title="${KIND_TITLE[cited.k]}">${cited.k}</span>
        <span>${link}</span>${method}
      </div>
    </div>`;
}

export function show(props: Record<string, unknown>, sources: Sources): void {
  const get = (k: string): Cited | undefined => {
    const v = props[k];
    return isCited(v) ? v : undefined;
  };

  const fuel = (get("fuel")?.v ?? "other") as Fuel;
  const gen = get("generation_gwh");

  el.innerHTML = `
    <button class="close" type="button" aria-label="Close">×</button>
    <div class="p-fuel" style="color:${FUEL_COLOR[fuel]}">
      <span style="width:9px;height:9px;border-radius:50%;background:${FUEL_COLOR[fuel]}"></span>
      ${FUEL_LABEL[fuel]}
    </div>
    <h2>${escapeHtml(String(props.name ?? "Unnamed"))}</h2>
    <p class="p-country">${escapeHtml(String(props.country ?? ""))} ·
      ${Number(props.lat).toFixed(3)}, ${Number(props.lon).toFixed(3)}</p>

    ${field("Capacity", get("capacity_mw"), (v: number) => power(v), sources)}
    ${field("Annual generation", gen, (v: number) => energy(v), sources)}
    ${field("Reported generation", get("generation_reported_gwh"),
            (v: number) => energy(v), sources)}
    ${field("Status", get("status"), (v: string) => cap(v), sources)}
    ${field("Commissioned", get("commissioned"), (v: number) => String(v), sources)}
    ${field("Operator", get("owner"), (v: string) => escapeHtml(v), sources)}
    ${field("Synchronous grid", get("region"), (v: string) => escapeHtml(v), sources)}

    ${divergence(gen, get("generation_reported_gwh"))}
    ${caveats(get("region_approximate"), get("capacity_factor_assumed"))}

    <div id="shed-summary" class="shed-box">Loading supply shed…</div>`;

  el.hidden = false;
  el.querySelector(".close")?.addEventListener("click", hide);
}

/** Where our estimate and the source's own disagree, say so rather than
 *  quietly showing one of them. */
function divergence(ours: Cited | undefined, reported: Cited | undefined): string {
  if (!ours || !reported) return "";
  const a = Number(ours.v), b = Number(reported.v);
  if (!(a > 0) || !(b > 0)) return "";
  const diff = a / b - 1;
  if (Math.abs(diff) < 0.15) return "";
  const dir = diff > 0 ? "above" : "below";
  return `<div class="p-warn">Our estimate is
    ${Math.abs(diff * 100).toFixed(0)}% ${dir} the figure the source reports.
    The two are shown separately rather than reconciled.</div>`;
}

/** Assumptions this plant's numbers rest on, stated rather than buried. */
function caveats(approxRegion: Cited | undefined, assumedCf: Cited | undefined): string {
  const notes: string[] = [];
  if (approxRegion?.v) {
    notes.push(`Grid region assigned by a geographic rule, not a published
      boundary — real synchronous boundaries are not open data.`);
  }
  if (assumedCf) {
    notes.push(`Generation uses a global default capacity factor
      (${Number(assumedCf.v).toFixed(2)}); this country and fuel are not in the
      reported data used for calibration.`);
  }
  if (!notes.length) return "";
  return `<div class="p-warn">${notes.map((n) => `<p>${n}</p>`).join("")}</div>`;
}

export interface ShedSummary {
  cells: number;
  populationServed: number;
  populationReached: number;
}

/**
 * Render the shed figures.
 *
 * Both population numbers are shown, labelled. Reporting only "people reached"
 * is the single most likely way this project would mislead: it is a much bigger,
 * much more quotable number, and it means something quite different from the
 * demand-weighted figure.
 */
export function setShedSummary(summary: ShedSummary | null): void {
  const box = document.getElementById("shed-summary");
  if (!box) return;

  if (!summary) {
    box.innerHTML = `<div class="shed-title">No modelled supply shed</div>
      <p>This plant's output could not be placed within its own synchronous grid
      region — usually because it exports over links the model does not
      represent, or sits far from any demand.</p>`;
    return;
  }

  box.innerHTML = `
    <div class="shed-title">Modelled supply shed
      <span class="kind modelled" title="${KIND_TITLE.modelled}">modelled</span>
    </div>
    <div class="shed-stats">
      <div>
        <div class="shed-num">${compact(summary.populationServed)}</div>
        <div class="shed-cap">people served <em>(demand-weighted)</em></div>
      </div>
      <div>
        <div class="shed-num">${compact(summary.populationReached)}</div>
        <div class="shed-cap">people receiving <em>some</em> of its power</div>
      </div>
    </div>
    <p>Spread across ${summary.cells.toLocaleString()} cells. Electrons are not
    tracked: this is where this plant's annual output would go under a
    distance-decay allocation constrained to match reported national generation
    and demand. Intermittency, dispatch order and storage are not modelled.</p>`;
}

function compact(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}bn`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return n.toFixed(0);
}

export function hide(): void {
  el.hidden = true;
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
