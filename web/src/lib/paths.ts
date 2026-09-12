/**
 * Resolve a data path against the deployment base.
 *
 * The app is served from the domain root in development and from `/omnigrid/`
 * on GitHub Pages. An absolute `/data/...` path silently resolves to the wrong
 * host root on a project Pages site, which 404s every dataset — the site loads,
 * the map draws, and nothing appears on it.
 *
 * `import.meta.env.BASE_URL` carries whatever `base` the build was given, with a
 * trailing slash, so everything that fetches data goes through here.
 */
export function dataUrl(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  return `${base.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}
