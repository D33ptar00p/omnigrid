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

    <div class="p-note">
      Supply sheds — the area each plant is estimated to serve — are not in this
      build yet. They arrive with the transport model.
    </div>`;

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
