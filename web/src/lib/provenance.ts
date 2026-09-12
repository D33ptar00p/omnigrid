/**
 * Client-side mirror of the pipeline's provenance types.
 *
 * The three kinds are rendered differently on purpose: a reader must be able to
 * tell a measurement from an estimate at a glance, without reading a footnote.
 */

export type Kind = "measured" | "derived" | "modelled";

export interface Cited<T = unknown> {
  /** value */ v: T;
  /** kind */ k: Kind;
  /** source id */ s: string;
  /** method (derived/modelled only) */ m?: string;
  /** contributing sources */ via?: string[];
}

export interface SourceMeta {
  id: string;
  name: string;
  short: string;
  publisher: string;
  version: string | null;
  url: string;
  licence: string;
  licence_url: string;
  attribution: string;
  role: string;
  citation: string;
  caveat?: string;
}

export interface Manifest {
  schema_version: number;
  built: string;
  model: Record<string, unknown>;
  validation: Record<string, unknown>;
  warnings: string[];
  sources: SourceMeta[];
  checksums: Record<string, string>;
}

export const KIND_LABEL: Record<Kind, string> = {
  measured: "measured",
  derived: "derived",
  modelled: "modelled",
};

export const KIND_TITLE: Record<Kind, string> = {
  measured: "Reported by the cited source.",
  derived: "Computed from cited sources by a named formula.",
  modelled: "Output of the OmniGrid supply-shed model — an estimate, not a measurement.",
};

export function isCited(x: unknown): x is Cited {
  return typeof x === "object" && x !== null && "v" in x && "k" in x && "s" in x;
}

export class Sources {
  private byId = new Map<string, SourceMeta>();

  constructor(public readonly manifest: Manifest) {
    for (const s of manifest.sources) this.byId.set(s.id, s);
  }

  get(id: string): SourceMeta | undefined {
    return this.byId.get(id);
  }

  /** Short label for inline citation, e.g. "GEM" or "WRI".
   *  Comes from the registry: deriving it from the publisher name produced
   *  "World" for "World Resources Institute". */
  short(id: string): string {
    return this.byId.get(id)?.short ?? id;
  }

  get all(): SourceMeta[] {
    return this.manifest.sources;
  }
}
