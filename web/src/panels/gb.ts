/** Detail panels for the GB view: plants and distribution regions. */

import { FUEL_COLOR, FUEL_LABEL, type Fuel } from "../lib/palette";
import { power } from "../lib/format";
import { KIND_TITLE, isCited, type Cited, type Sources } from "../lib/provenance";
import { fuelBreakdown, type RegionProps } from "../gb/view";

const el = document.getElementById("panel") as HTMLElement;

function cite(c: Cited, sources: Sources): string {
  const src = sources.get(c.s);
  const link = src
    ? `<a href="${src.url}" target="_blank" rel="noopener">${sources.short(c.s)}</a>`
    : c.s;
  return `<div class="cite">
    <span class="kind ${c.k}" title="${KIND_TITLE[c.k]}">${c.k}</span><span>${link}</span>
  </div>`;
}

function field(label: string, c: Cited | undefined, render: (v: never) => string,
               sources: Sources): string {
  if (!c || c.v === null || c.v === undefined || c.v === "") return "";
  return `<div class="field">
    <div class="field-label">${label}</div>
    <div class="field-value">${render(c.v as never)}</div>
    ${cite(c, sources)}
  </div>`;
}

export function showPlant(props: Record<string, unknown>, sources: Sources): void {
  const get = (k: string): Cited | undefined => {
    const v = props[k];
    return isCited(v) ? v : undefined;
  };
  const fuel = (get("fuel")?.v ?? "other") as Fuel;
  const matched = props.matched_unit as string | undefined;
  const basis = props.match_basis as string | undefined;

  const image = props.image as Record<string, string | null> | undefined;

  el.innerHTML = `
    <button class="close" type="button" aria-label="Close">×</button>
    ${image?.thumb ? `
      <figure class="plant-photo">
        <img src="${image.thumb}" alt="${esc(String(props.name ?? "Power station"))}"
             loading="lazy"
             onerror="this.closest('figure').remove()">
        <figcaption>
          ${image.artist ? esc(image.artist) : "Unknown author"}
          ${image.licence ? ` · ${esc(image.licence)}` : ""}
          ${image.credit_url ? ` · <a href="${image.credit_url}" target="_blank"
             rel="noopener">Commons</a>` : ""}
        </figcaption>
      </figure>` : ""}
    <div class="p-fuel" style="color:${FUEL_COLOR[fuel]}">
      <span style="width:9px;height:9px;border-radius:50%;background:${FUEL_COLOR[fuel]}"></span>
      ${FUEL_LABEL[fuel]}
    </div>
    <h2>${esc(String(props.name ?? "Unnamed"))}</h2>
    <p class="p-country">${Number(props.lat).toFixed(4)}, ${Number(props.lon).toFixed(4)}</p>

    ${field("Capacity", get("capacity_mw"), (v: number) => power(v), sources)}
    ${field("Operator", get("operator"), (v: string) => esc(v), sources)}

    ${props.off_gb_network ? `
      <div class="p-warn"><p>Outside every GB distribution licence area.
      Northern Ireland is on the all-island Irish system; the Isle of Man and
      Channel Islands are separate again. This station is real, but it is not on
      the GB grid and is excluded from GB totals.</p></div>
    ` : props.located_in ? `
      <div class="field">
        <div class="field-label">Located in</div>
        <div class="field-value">${esc(String(props.located_in))}</div>
        <div class="cite">
          <span class="kind measured" title="Where the station physically sits. Not a claim about who it supplies.">located in</span>
          <span>point-in-polygon against
            <a href="${sources.get("neso_dno_areas")?.url}" target="_blank" rel="noopener">NESO</a> boundaries</span>
        </div>
      </div>` : ""}

    ${matched ? `
      <div class="field">
        <div class="field-label">Elexon BM Unit</div>
        <div class="field-value mono">${esc(matched)}</div>
        <div class="cite">
          <span class="kind linked" title="A record match made by us, not an identifier published by either source.">record link</span>
        </div>
      </div>
      <div class="p-warn"><p>${esc(basis ?? "")}</p></div>
    ` : `
      <div class="p-note">Not matched to a Balancing Mechanism Unit. Most GB
      plants are too small to be metered individually in the balancing market,
      and matching is only accepted on an exact, unique name.</div>
    `}`;

  el.hidden = false;
  el.querySelector(".close")?.addEventListener("click", hide);
}

export function showRegion(props: RegionProps, sources: Sources): void {
  const mix = fuelBreakdown(props);
  const total = mix.reduce((a, [, mw]) => a + mw, 0) + (Number(props.fuel_undeclared_mw) || 0);
  const undeclared = Number(props.fuel_undeclared_mw) || 0;

  el.innerHTML = `
    <button class="close" type="button" aria-label="Close">×</button>
    <div class="p-fuel" style="color:var(--ink-dim)">Distribution region</div>
    <h2>${esc(props.area)}</h2>
    <p class="p-country">${esc(props.dno_full)} · GSP group
      <span class="mono">${esc(props.code)}</span></p>

    <div class="field">
      <div class="field-label">Embedded generation connected here</div>
      <div class="field-value">${power(Number(props.embedded_capacity_mw))}</div>
      <div class="cite">
        <span class="kind measured" title="${KIND_TITLE.measured}">measured</span>
        <span>${props.embedded_units} units ·
          <a href="${sources.get("elexon_bmu")?.url}" target="_blank" rel="noopener">Elexon</a>
        </span>
      </div>
    </div>

    ${mix.length ? `
      <div class="field">
        <div class="field-label">Fuel mix of embedded generation</div>
        ${undeclared / total > 0.4 ? `<p class="mixwarn">Elexon declares no fuel
          for ${((undeclared / total) * 100).toFixed(0)}% of this capacity.</p>` : ""}
        <div class="mixbar">${mix.map(([f, mw]) =>
          `<span style="width:${(mw / total) * 100}%;background:${FUEL_COLOR[f] ?? "#3a4759"}"
                 title="${FUEL_LABEL[f] ?? f}: ${power(mw)}"></span>`).join("")}
          ${undeclared > 0
            ? `<span style="width:${(undeclared / total) * 100}%;background:#3a4759"
                     title="Fuel not declared: ${power(undeclared)}"></span>` : ""}
        </div>
        <ul class="mixlist">
          ${mix.map(([f, mw]) => `<li>
            <span class="swatch" style="background:${FUEL_COLOR[f] ?? "#3a4759"}"></span>
            ${FUEL_LABEL[f] ?? f}<b>${power(mw)}</b></li>`).join("")}
          ${undeclared > 0 ? `<li>
            <span class="swatch" style="background:#3a4759"></span>
            Fuel not declared<b>${power(undeclared)}</b></li>` : ""}
        </ul>
      </div>` : ""}

    <div class="p-note">
      This region's boundary is published by NESO, and Elexon publishes which
      units feed it.
      ${undeclared > 0 ? `Elexon declares no fuel type for ${power(undeclared)}
      of this capacity; it is shown as undeclared rather than guessed.` : ""}
      <br><br>
      Transmission-connected stations are <em>not</em> counted here. They feed the
      GB national grid rather than any one region.
    </div>`;

  el.hidden = false;
  el.querySelector(".close")?.addEventListener("click", hide);
}

export function hide(): void {
  el.hidden = true;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
