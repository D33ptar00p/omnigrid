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
 * network is a single connected graph — Drax reaches 92% of it — which is
 * precisely why a per-station catchment area does not exist. Showing the trace
 * by hop distance makes that visible instead of asserting it.
 */

export interface Trace {
  /** line index -> hops from the station */
  hops: Map<number, number>;
  /** lines the station connects to directly */
  roots: number[];
  /** lines reachable at any distance, i.e. its connected component */
  componentSize: number;
  totalLines: number;
}

export class GridTracer {
  private adjacency = new Map<number, number[]>();
  private connections: Record<string, number[]> = {};
  private componentCache = new Map<number, number>();
  ready = false;

  async init(base = "/data/gb"): Promise<void> {
    const [adj, conns] = await Promise.all([
      fetch(`${base}/adjacency.json`).then((r) => r.json()),
      fetch(`${base}/connections.json`).then((r) => r.json()),
    ]);
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
  trace(plantId: string, maxHops = 12): Trace | null {
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
    return {
      hops, roots,
      componentSize: this.componentSize(roots[0]!),
      totalLines: this.adjacency.size,
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
