/**
 * Trace the physical grid outward from a power station.
 *
 * Lines join end-to-end within a run, but separate runs meet at a substation
 * rather than at each other — so substations are what make the network one
 * connected grid. The pipeline builds that adjacency from surveyed
 * OpenStreetMap geometry, and this walks it breadth-first.
 *
 * The trace answers "what is this station wired to", which is a question of
 * fact. It is not a claim about where the electricity goes. The GB transmission
 * network is a single connected graph — Drax reaches 54% of every mapped line
 * in GB, and that share is much the same for any connected station — which is
 * precisely why a per-station catchment area does not exist. The share is
 * therefore reported as a figure, and the map draws the local connection, which
 * is what actually differs between stations.
 */

export interface Trace {
  /** line index -> hops from the station */
  hops: Map<number, number>;
  /** lines the station connects to directly */
  roots: number[];
  /** lines reachable at any distance, i.e. its connected component */
  componentSize: number;
  totalLines: number;
  /** highest voltage among the lines terminating at the station */
  voltage: number | null;
  /** share of the network reachable, as computed over the full all-voltage graph */
  share: number;
  maxHops: number;
}

export interface Reach {
  lines: number;
  voltage: number | null;
  component: number;
  share: number;
}

/**
 * How far to walk by default.
 *
 * Three hops, not the whole component. Reach is ~92% of the network for nearly
 * every connected plant in GB, so drawing the full component renders a 5 MW
 * solar farm and Drax identically — the same picture for every input, which
 * conveys nothing. The local connection is what actually differs, and the 92%
 * is reported as a figure instead.
 */
export const DEFAULT_HOPS = 3;
export const MAX_HOPS = 14;

export class GridTracer {
  private adjacency = new Map<number, number[]>();
  private connections: Record<string, number[]> = {};
  private reach: Record<string, Reach> = {};
  private componentCache = new Map<number, number>();
  ready = false;

  async init(base = "/data/gb"): Promise<void> {
    const [adj, conns, reach] = await Promise.all([
      fetch(`${base}/adjacency.json`).then((r) => r.json()),
      fetch(`${base}/connections.json`).then((r) => r.json()),
      fetch(`${base}/reach.json`).then((r) => r.json()),
    ]);
    this.reach = reach;
    for (const [k, v] of Object.entries(adj as Record<string, number[]>)) {
      this.adjacency.set(Number(k), v);
    }
    this.connections = conns;
    this.ready = true;
  }

  get totalLines(): number {
    return this.adjacency.size;
  }

  isWired(plantId: string): boolean {
    return (this.connections[plantId]?.length ?? 0) > 0;
  }

  /** Breadth-first walk outward, capped so the picture stays legible. */
  trace(plantId: string, maxHops = DEFAULT_HOPS): Trace | null {
    const roots = this.connections[plantId];
    if (!roots?.length) return null;

    const hops = new Map<number, number>();
    for (const r of roots) hops.set(r, 0);
    const queue = [...roots];
    let head = 0;
    while (head < queue.length) {
      const cur = queue[head++]!;
      const d = hops.get(cur)!;
      if (d >= maxHops) continue;
      for (const next of this.adjacency.get(cur) ?? []) {
        if (!hops.has(next)) {
          hops.set(next, d + 1);
          queue.push(next);
        }
      }
    }
    const reach = this.reach[plantId];
    return {
      hops, roots,
      componentSize: reach?.component ?? this.componentSize(roots[0]!),
      totalLines: this.adjacency.size,
      voltage: reach?.voltage ?? null,
      // Share comes from the pipeline, measured over the full all-voltage
      // graph rather than the subset shipped for drawing.
      share: reach?.share ?? 0,
      maxHops,
    };
  }

  /** Full reach, uncapped — how much of the network this station is wired to. */
  private componentSize(start: number): number {
    const cached = this.componentCache.get(start);
    if (cached !== undefined) return cached;

    const seen = new Set<number>([start]);
    const queue = [start];
    let head = 0;
    while (head < queue.length) {
      for (const next of this.adjacency.get(queue[head++]!) ?? []) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
    // Every line in a component shares its size; cache for all of them.
    for (const line of seen) this.componentCache.set(line, seen.size);
    return seen.size;
  }
}
