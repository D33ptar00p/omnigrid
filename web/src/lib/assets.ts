/**
 * Load the global asset set.
 *
 * The pipeline ships fields column-wise rather than as GeoJSON: 145,396 plants
 * as GeoJSON is 87 MB, most of it the same `{"type":"Feature",...}` scaffolding
 * repeated per point. Columns are 8.9 MB, and rebuilding GeoJSON here costs a
 * fraction of a second.
 *
 * Detail beyond what the map draws — owner, commissioning year, and the
 * provenance of every field — is fetched per plant by HTTP Range, so clicking
 * costs only that plant's bytes.
 */

import { dataUrl } from "./paths";
import type { Cited } from "./provenance";

interface PackedPoints {
  count: number;
  fuels: string[];
  statuses: string[];
  lon: number[];
  lat: number[];
  fuel: number[];
  mw: number[];
  status: number[];
  name: string[];
}

export interface AssetDetail {
  id: string;
  name: string;
  country: string;
  lat: number;
  lon: number;
  [key: string]: Cited | string | number | undefined;
}

export class AssetStore {
  private index: [number, number][] = [];
  private cache = new Map<number, AssetDetail>();
  ready = false;
  count = 0;

  constructor(private base = "data") {}

  /** Fetch the columns and rebuild them into a GeoJSON source. */
  async load(): Promise<GeoJSON.FeatureCollection> {
    const [packed, index] = await Promise.all([
      fetch(dataUrl(`${this.base}/assets.points.json`)).then((r) => r.json() as Promise<PackedPoints>),
      fetch(dataUrl(`${this.base}/assets.detail.idx.json`)).then((r) => r.json()),
    ]);
    this.index = index;
    this.count = packed.count;
    this.ready = true;

    const features = new Array<GeoJSON.Feature>(packed.count);
    for (let i = 0; i < packed.count; i++) {
      features[i] = {
        type: "Feature",
        id: i,
        geometry: { type: "Point", coordinates: [packed.lon[i]!, packed.lat[i]!] },
        properties: {
          i,
          name: packed.name[i],
          _fuel: packed.fuels[packed.fuel[i]!],
          _mw: packed.mw[i],
          _status: packed.statuses[packed.status[i]!],
        },
      };
    }
    return { type: "FeatureCollection", features };
  }

  /** Full record for one plant, with per-field provenance. */
  async detail(i: number): Promise<AssetDetail | null> {
    const cached = this.cache.get(i);
    if (cached) return cached;

    const entry = this.index[i];
    if (!entry) return null;
    const [offset, length] = entry;

    const res = await fetch(dataUrl(`${this.base}/assets.detail.bin`), {
      headers: { Range: `bytes=${offset}-${offset + length - 1}` },
    });
    if (!res.ok && res.status !== 206) return null;

    // Each record is gzipped independently so it can be range-fetched.
    const stream = res.body?.pipeThrough(new DecompressionStream("gzip"));
    const text = stream
      ? await new Response(stream).text()
      : await res.text();
    const detail = JSON.parse(text) as AssetDetail;

    if (this.cache.size > 128) this.cache.delete(this.cache.keys().next().value!);
    this.cache.set(i, detail);
    return detail;
  }
}
