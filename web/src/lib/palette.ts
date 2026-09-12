/**
 * The fuel palette. Colour is the primary encoding in this app, so it lives in
 * one place and drives points, legend and panel alike.
 *
 * Structure carries meaning before the legend is read: fossil fuels take warm
 * earth tones, renewables cool and bright ones, nuclear a violet of its own.
 * Solar is the deliberate exception -- it sits warm, because "solar is yellow" is
 * a strong enough convention that breaking it would cost more than the slightly
 * weaker warm/cool split.
 *
 * Lightness varies across the set as well as hue, so the categories stay
 * separable under the common colour-vision deficiencies and on a dark ground.
 */

import type { ExpressionSpecification } from "maplibre-gl";

export const FUEL_ORDER = [
  "coal", "oil", "gas", "nuclear", "hydro",
  "wind", "solar", "geothermal", "bioenergy", "other",
] as const;

export type Fuel = (typeof FUEL_ORDER)[number];

export const FUEL_COLOR: Record<Fuel, string> = {
  coal:       "#8a6250",
  oil:        "#c2543d",
  gas:        "#e07b39",
  nuclear:    "#b85cd6",
  hydro:      "#2e86c1",
  wind:       "#56c6b9",
  solar:      "#f5d547",
  geothermal: "#e05c8a",
  bioenergy:  "#6bbf59",
  other:      "#8a94a6",
};

export const FUEL_LABEL: Record<Fuel, string> = {
  coal: "Coal", oil: "Oil", gas: "Gas", nuclear: "Nuclear", hydro: "Hydro",
  wind: "Wind", solar: "Solar", geothermal: "Geothermal",
  bioenergy: "Bioenergy", other: "Other",
};

export const FOSSIL: ReadonlySet<Fuel> = new Set<Fuel>(["coal", "oil", "gas"]);

/**
 * MapLibre `match` expression mapping the flat `_fuel` property to a colour.
 *
 * Built here rather than spread at the call site: a spread into `match` loses
 * the tuple shape TypeScript needs to check the expression, and the cast is
 * better contained in the one module that owns the palette.
 */
export function fuelColorExpression(): ExpressionSpecification {
  const stops = FUEL_ORDER.flatMap((f) => [f, FUEL_COLOR[f]]);
  return ["match", ["get", "_fuel"], ...stops, FUEL_COLOR.other] as unknown as ExpressionSpecification;
}
