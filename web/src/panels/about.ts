/**
 * The sources panel. Rendered entirely from the build manifest, so it cannot
 * claim a dataset the build did not use, or omit one it did.
 */

import type { SourceMeta, Sources } from "../lib/provenance";

const panel = document.getElementById("about") as HTMLElement;
const toggle = document.getElementById("about-toggle") as HTMLButtonElement;

const ROLE_HEADINGS: [string, string][] = [
  ["input", "Data sources"],
  ["model", "Modelled by OmniGrid"],
  ["validation", "Held out for validation"],
  ["basemap", "Basemap"],
];

/**
 * When this source was last refreshed.
 *
 * Two different dates, kept apart on purpose: `fetched` is when our copy was
 * written, `data_date` is the moment the data itself describes. For metered
 * generation those differ by days — B1610 is settlement data and lags real time
 * — and conflating them would imply the map is live when it is not.
 */
function dateline(s: SourceMeta): string {
  const bits: string[] = [];
  if (s.data_date) bits.push(`Data for ${s.data_date}`);
  if (s.fetched) bits.push(`${s.data_date ? "fetched" : "Fetched"} ${s.fetched}`);
  return bits.length ? `<div class="src-date">${bits.join(" · ")}</div>` : "";
}

export function init(sources: Sources): void {
  const { manifest } = sources;

  const groups = ROLE_HEADINGS.map(([role, heading]) => {
    const items = sources.all.filter((s) => s.role === role);
    if (!items.length) return "";
    return `<h3>${heading}</h3>` + items.map((s) => `
      <div class="src">
        <div class="src-name">${s.name}</div>
        <div class="src-meta">
          ${s.publisher}${s.version ? ` · ${s.version}` : ""} ·
          <a href="${s.licence_url}" target="_blank" rel="noopener">${s.licence}</a> ·
          <a href="${s.url}" target="_blank" rel="noopener">source</a>
        </div>
        ${dateline(s)}
        ${s.caveat ? `<div class="src-caveat">${s.caveat}</div>` : ""}
      </div>`).join("");
  }).join("");

  panel.innerHTML = `
    <h2>Where this data comes from</h2>
    <p class="sub">Every figure on the map is traceable to one of these, and each
      value shows which one it came from. Nothing here is modelled.</p>
    <div class="build-line">
      <span>Last built</span><b>${manifest.built}</b>
    </div>
    ${groups}`;

  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    toggle.classList.toggle("on", !panel.hidden);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      panel.hidden = true;
      toggle.classList.remove("on");
    }
  });
}
