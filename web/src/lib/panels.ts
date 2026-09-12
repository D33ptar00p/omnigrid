/**
 * The bottom-left panel slot.
 *
 * The legend and the sources panel both open in the same place above the
 * control bar, so exactly one may be visible at a time. The rule lives here
 * rather than in either panel: `main.ts` already imports `panels/about`, so
 * having `about` import back from `main` would create a cycle.
 */

const BOTTOM_PANELS: readonly (readonly [string, string])[] = [
  ["legend", "legend-toggle"],
  ["about", "about-toggle"],
];

/** Hide every bottom panel and clear the active state from its toggle. */
export function closeBottomPanels(): void {
  for (const [panelId, toggleId] of BOTTOM_PANELS) {
    const panel = document.getElementById(panelId);
    if (panel) panel.hidden = true;
    document.getElementById(toggleId)?.classList.remove("on");
  }
}

/** Open one bottom panel, closing whichever other one was open. */
export function togglePanel(panelId: string, toggleId: string): void {
  const panel = document.getElementById(panelId);
  const toggle = document.getElementById(toggleId);
  if (!panel || !toggle) return;

  const opening = panel.hidden;
  closeBottomPanels();
  panel.hidden = !opening;
  toggle.classList.toggle("on", opening);
}
