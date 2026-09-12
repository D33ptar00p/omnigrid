/**
 * The sources panel. Rendered entirely from the build manifest, so it cannot
 * claim a dataset the build did not use, or omit one it did.
 */

import type { Sources } from "../lib/provenance";

const panel = document.getElementById("about") as HTMLElement;
const toggle = document.getElementById("about-toggle") as HTMLButtonElement;

const ROLE_HEADINGS: [string, string][] = [
  ["input", "Data sources"],
  ["model", "Modelled by OmniGrid"],
  ["validation", "Held out for validation"],
  ["basemap", "Basemap"],
];

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
        ${s.caveat ? `<div class="src-caveat">${s.caveat}</div>` : ""}
      </div>`).join("");
  }).join("");

  panel.innerHTML = `
    <h2>Where this data comes from</h2>
    <p class="sub">Build ${manifest.built}. Every figure on the map is traceable to
      one of these. Values are marked <em>measured</em>, <em>derived</em> or
      <em>modelled</em> so an estimate never reads as a measurement.</p>
    ${groups}`;

  toggle.addEventListener("click", () => { panel.hidden = !panel.hidden; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") panel.hidden = true;
  });
}
