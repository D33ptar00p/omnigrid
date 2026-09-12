/**
 * Fetch and decode one plant's supply shed.
 *
 * Sheds live in a single concatenated blob, addressed by HTTP Range. One file
 * rather than 90k means CDNs and git stay usable; Range means a click costs only
 * the bytes of that shed, typically a few kilobytes.
 *
 * Record layout, little-endian, matching pipeline/pack/sheds.py:
 *   magic "OGSH" | u8 version | u8 _ | u16 _ | u32 count
 *   f32 gwh | f32 population_served | f32 population_reached
 *   u32[count] cell indices into cells.bin
 *   u8[count]  share, sqrt-companded
 */

import { cellToBoundary } from "h3-js";

const MAGIC = 0x4853474f; // "OGSH" little-endian

export interface ShedIndexEntry {
  /** byte offset */ o: number;
  /** byte length */ n: number;
  /** cell count */ c: number;
  gwh: number;
  pop: number;
  reach: number;
}

export interface Shed {
  plantId: string;
  cells: string[];
  /** Share of this plant's output reaching each cell, 0..1. */
  shares: Float32Array;
  gwh: number;
  populationServed: number;
  populationReached: number;
}

export class ShedStore {
  private index: Record<string, ShedIndexEntry> = {};
  private cells: BigUint64Array | null = null;
  /** Cached H3 string ids, built lazily: converting 71k BigInts up front costs
   *  more than most sessions will ever use. */
  private cellIds: (string | undefined)[] = [];
  private cache = new Map<string, Shed>();
  ready = false;

  constructor(private base = "/data/shed") {}

  async init(): Promise<void> {
    const [idx, cells] = await Promise.all([
      fetch(`${this.base}/sheds.idx.json`).then((r) => r.json()),
      fetch(`${this.base}/cells.bin`).then((r) => r.arrayBuffer()),
    ]);
    this.index = idx;
    this.cells = new BigUint64Array(cells);
    this.cellIds = new Array(this.cells.length);
    this.ready = true;
  }

  has(plantId: string): boolean {
    return plantId in this.index;
  }

  stats(plantId: string): ShedIndexEntry | undefined {
    return this.index[plantId];
  }

  private cellId(i: number): string {
    let id = this.cellIds[i];
    if (id === undefined) {
      id = this.cells![i]!.toString(16).padStart(15, "0");
      this.cellIds[i] = id;
    }
    return id;
  }

  async load(plantId: string): Promise<Shed | null> {
    const cached = this.cache.get(plantId);
    if (cached) return cached;

    const entry = this.index[plantId];
    if (!entry || entry.c === 0) return null;

    const res = await fetch(`${this.base}/sheds.bin`, {
      headers: { Range: `bytes=${entry.o}-${entry.o + entry.n - 1}` },
    });
    if (!res.ok && res.status !== 206) {
      throw new Error(`shed fetch failed: ${res.status}`);
    }
    const buf = await res.arrayBuffer();
    const shed = decode(plantId, buf, (i) => this.cellId(i));

    // Bounded cache: sheds are small, but a long session clicking through
    // thousands of plants should not grow without limit.
    if (this.cache.size > 64) this.cache.delete(this.cache.keys().next().value!);
    this.cache.set(plantId, shed);
    return shed;
  }
}

function decode(plantId: string, buf: ArrayBuffer, cellId: (i: number) => string): Shed {
  const view = new DataView(buf);
  if (view.getUint32(0, true) !== MAGIC) {
    throw new Error("shed record: bad magic — index and blob are out of step");
  }
  const count = view.getUint32(8, true);
  const gwh = view.getFloat32(12, true);
  const pop = view.getFloat32(16, true);
  const reach = view.getFloat32(20, true);

  const HEADER = 24;
  const idx = new Uint32Array(buf.slice(HEADER, HEADER + count * 4));
  const quant = new Uint8Array(buf, HEADER + count * 4, count);

  const cells = new Array<string>(count);
  const shares = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    cells[i] = cellId(idx[i]!);
    // Undo the sqrt companding applied at pack time.
    const s = quant[i]! / 255;
    shares[i] = s * s;
  }
  return { plantId, cells, shares, gwh, populationServed: pop, populationReached: reach };
}

/** Shed cells as GeoJSON, carrying share so the style can ramp opacity. */
export function toGeoJSON(shed: Shed): GeoJSON.FeatureCollection {
  const max = shed.shares.length ? Math.max(...shed.shares) : 1;
  return {
    type: "FeatureCollection",
    features: shed.cells.map((cell, i) => {
      const ring = cellToBoundary(cell, true); // [lng, lat]
      return {
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates: [ring] },
        properties: {
          // Relative to the shed's own peak: an absolute ramp would make every
          // large plant's shed uniformly faint.
          intensity: max > 0 ? shed.shares[i]! / max : 0,
          share: shed.shares[i],
        },
      };
    }),
  };
}
