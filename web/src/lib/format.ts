/** Number formatting. Kept central so the panel and tooltip never disagree. */

export function power(mw: number): string {
  if (mw >= 1000) return `${(mw / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} GW`;
  return `${mw.toLocaleString(undefined, { maximumFractionDigits: 1 })} MW`;
}

export function energy(gwh: number): string {
  if (gwh >= 1000) return `${(gwh / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} TWh`;
  return `${gwh.toLocaleString(undefined, { maximumFractionDigits: 0 })} GWh`;
}

export function count(n: number): string {
  return n.toLocaleString();
}
