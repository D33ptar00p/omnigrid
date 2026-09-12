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

  // Before the detail record arrives, only the render fields are present.
  const fuel = (get("fuel")?.v ?? props._fuel ?? "other") as Fuel;
  const gen = get("generation_gwh");

  el.innerHTML = `
    <button class="close" type="button" aria-label="Close">×</button>
    <div class="p-fuel" style="color:${FUEL_COLOR[fuel]}">
      <span style="width:9px;height:9px;border-radius:50%;background:${FUEL_COLOR[fuel]}"></span>
      ${FUEL_LABEL[fuel]}
    </div>
    <h2>${escapeHtml(String(props.name ?? "Unnamed"))}</h2>
    <p class="p-country">${escapeHtml(String(props.country ?? ""))}${
      props.lat !== undefined
        ? ` · ${Number(props.lat).toFixed(3)}, ${Number(props.lon).toFixed(3)}`
        : ""}</p>

    ${field("Capacity", get("capacity_mw"), (v: number) => power(v), sources)}
    ${field("Annual generation", gen, (v: number) => energy(v), sources)}

    ${field("Status", get("status"), (v: string) => cap(v), sources)}
    ${field("Commissioned", get("commissioned"), (v: number) => String(v), sources)}
    ${field("Operator", get("owner"), (v: string) => escapeHtml(v), sources)}
`;

  el.hidden = false;
  el.querySelector(".close")?.addEventListener("click", hide);
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
