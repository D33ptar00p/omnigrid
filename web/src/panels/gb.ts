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
  const units = (props.operator_units ?? []) as OperatorUnit[];

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
      <div class="p-warn"><p>${props.other_system
        ? esc(String(props.other_system)) + ". Real, but not on the GB grid, and excluded from GB totals."
        : "On " + esc(String(props.foreign_country ?? "another country")) +
          "'s grid, not GB's. Shown because it is within the map's bounds."}</p></div>
    ` : props.offshore ? `
      <div class="field">
        <div class="field-label">Connection</div>
        <div class="field-value">Offshore</div>
        <div class="cite">
          <span class="kind measured" title="Position is surveyed; the offshore classification follows from it.">offshore</span>
          <span>outside every DNO area — those cover onshore distribution —
            but on the GB transmission system</span>
        </div>
      </div>
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

    <div id="trace-box" class="trace-box">Tracing the grid…</div>

    ${operatorUnits(props, sources)}

    ${matched ? `
      <div class="field">
        <div class="field-label">Elexon BM Unit</div>
        <div class="field-value mono">${esc(matched)}</div>
        <div class="cite">
          <span class="kind linked" title="A record match made by us, not an identifier published by either source.">record link</span>
        </div>
      </div>
      <div class="p-warn"><p>${esc(basis ?? "")}</p></div>
    ` : units.length ? "" : `
      <div class="p-note">Not matched to a Balancing Mechanism Unit. Most GB
      plants are too small to be metered individually in the balancing market,
      and matching is only accepted on an exact, unique name.</div>
    `}`;

  el.hidden = false;
  el.querySelector(".close")?.addEventListener("click", hide);
}

interface OperatorUnit {
  bm_unit: string;
  capacity_mw: number | null;
  fuel: string | null;
  operator: string | null;
  metered_mwh: number | null;
}

/**
 * Elexon units run by the same company.
 *
 * Elexon names most large stations only by BM Unit code — Drax is T_DRAXX-1
 * through -6 — so a station-level name match is impossible for exactly the
 * plants people most want to look at. These units are linked by operator, which
 * is weaker, and the label says so: same company, not necessarily this station.
 */
function operatorUnits(props: Record<string, unknown>, sources: Sources): string {
  const units = (props.operator_units ?? []) as OperatorUnit[];
  if (!units.length) return "";

  const rows = units.slice(0, 12).map((u) => {
    const mw = u.metered_mwh !== null ? u.metered_mwh * 2 : null; // half-hour → MW
    return `<li>
      <span class="mono">${esc(u.bm_unit)}</span>
      <span class="u-cap">${u.capacity_mw !== null ? power(u.capacity_mw) : "—"}</span>
      <span class="u-out ${mw !== null && mw > 1 ? "on" : ""}">
        ${mw === null ? "" : mw > 1 ? `${power(mw)} now` : "off"}
      </span>
    </li>`;
  }).join("");

  return `<div class="field">
    <div class="field-label">Metered units run by this operator</div>
    <ul class="unitlist">${rows}</ul>
    ${units.length > 12 ? `<p class="u-more">+ ${units.length - 12} more</p>` : ""}
    <div class="cite">
      <span class="kind linked" title="Linked by company name, not by station. These units are run by the same operator; they are not necessarily this station.">same operator</span>
      <span>output metered by
        <a href="${sources.get("elexon_b1610")?.url}" target="_blank" rel="noopener">Elexon</a>
      </span>
    </div>
  </div>`;
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

import { MAX_HOPS, type Trace } from "../gb/trace";

/**
 * Report what this station is physically wired to.
 *
 * The component figure is the honest headline: Drax reaches 92% of the GB
 * transmission network, which is why asking "which area does Drax supply" has
 * no answer. Saying so plainly beats drawing a boundary that implies one.
 */
export function setTrace(trace: Trace | null, onHops?: (hops: number) => void): void {
  const box = document.getElementById("trace-box");
  if (!box) return;

  if (!trace) {
    box.innerHTML = `<div class="trace-title">Grid connection</div>
      <p>No power line terminates within 1 km. A line passing overhead is not a
      connection, so proximity alone does not count. Most small generators
      connect at low voltage, which OpenStreetMap maps less completely.</p>`;
    return;
  }

  const kv = trace.voltage ? `${(trace.voltage / 1000).toFixed(0)} kV` : "—";
  const drawn = trace.hops.size;

  box.innerHTML = `
    <div class="trace-title">Grid connection
      <span class="kind measured" title="Traced through surveyed OpenStreetMap geometry.">surveyed</span>
    </div>
    <div class="trace-stats">
      <div><div class="trace-num">${kv}</div>
        <div class="trace-cap">connection voltage</div></div>
      <div><div class="trace-num">${trace.roots.length}</div>
        <div class="trace-cap">line${trace.roots.length === 1 ? "" : "s"} terminating here</div></div>
    </div>

    <label class="hopctl">
      <span>Follow the wires <b>${trace.maxHops}</b> hop${trace.maxHops === 1 ? "" : "s"}
        — ${drawn.toLocaleString()} lines shown</span>
      <input type="range" id="hop-range" min="1" max="${MAX_HOPS}" value="${trace.maxHops}">
    </label>

    <p>Keep going and this reaches <b>${(trace.share * 100).toFixed(0)}%</b> of the
    mapped network. That figure is nearly the same for every connected station in
    Britain, which is why it is written rather than drawn: the grid is one
    connected graph, so no station has a catchment area of its own. What differs
    between stations is the connection itself — voltage and how many circuits —
    so that is what the map shows.</p>`;

  const range = box.querySelector("#hop-range") as HTMLInputElement | null;
  range?.addEventListener("input", () => onHops?.(Number(range.value)));
}

export function hide(): void {
  el.hidden = true;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
