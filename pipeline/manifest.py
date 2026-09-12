"""Generate every attribution surface from the registry.

The in-app attribution panel, the methodology reference list, DATA_SOURCES.md and
the shipped manifest.json all come from here. That is the whole point: they are
derived from one file, so they cannot disagree with each other or with what the
pipeline actually read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pipeline.sources.registry import Registry, Source, load, sha256

DIST = Path(__file__).resolve().parent.parent / "data" / "dist"
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class BuildManifest:
    """What this build actually used. Written alongside the tiles and shipped."""

    built: str = field(default_factory=lambda: date.today().isoformat())
    schema_version: int = 1
    used: set[str] = field(default_factory=set)
    checksums: dict[str, str] = field(default_factory=dict)
    #: source_id -> ISO date the local copy was last written. For a live API
    #: this is when we fetched it; for a vendored file, when it was placed.
    #: Distinct from the dataset's own release version, which the registry holds.
    fetched: dict[str, str] = field(default_factory=dict)
    #: source_id -> the date the *data itself* refers to, where that differs
    #: from when we fetched it (a settlement date, a survey date).
    data_dates: dict[str, str] = field(default_factory=dict)
    model_params: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def record_use(self, *source_ids: str) -> None:
        self.used.update(source_ids)

    def record_input(self, source_id: str, path: Path) -> None:
        """Checksum a raw input so a silent upstream change cannot pass unnoticed,
        and record when this copy of it was last written."""
        self.record_use(source_id)
        self.checksums[f"{source_id}:{path.name}"] = sha256(path)
        self.fetched[source_id] = date.fromtimestamp(path.stat().st_mtime).isoformat()

    def record_data_date(self, source_id: str, when: str) -> None:
        """The date the data describes, when that is not the date we fetched it."""
        self.data_dates[source_id] = when

    def to_json(self, reg: Registry) -> dict[str, Any]:
        sources = reg.resolve(self.used)
        return {
            "schema_version": self.schema_version,
            "built": self.built,
            "model": self.model_params,
            "validation": self.validation,
            "warnings": self.warnings,
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "short": s.short,
                    "publisher": s.publisher,
                    "version": s.version,
                    "url": s.url,
                    "licence": s.licence,
                    "licence_url": s.licence_url,
                    "attribution": s.attribution,
                    "role": s.role,
                    "citation": s.citation(accessed=self.built),
                    "fetched": self.fetched.get(s.id),
                    "data_date": self.data_dates.get(s.id),
                    **({"caveat": s.notes} if s.notes else {}),
                }
                for s in sources
            ],
            "checksums": self.checksums,
        }

    def write(self, reg: Registry, dist: Path = DIST) -> Path:
        dist.mkdir(parents=True, exist_ok=True)
        out = dist / "manifest.json"
        out.write_text(json.dumps(self.to_json(reg), indent=2, sort_keys=False) + "\n")
        return out


def _wrap(text: str, width: int = 88, indent: str = "  ") -> str:
    import textwrap

    return "\n".join(textwrap.wrap(" ".join(text.split()), width, initial_indent=indent,
                                   subsequent_indent=indent))


def render_data_sources_md(reg: Registry, used: set[str] | None = None) -> str:
    """Human-readable reference list. Same data as the panel, prose form."""
    roles = [
        ("input", "Model inputs", "Data that feeds the map and the supply-shed model."),
        ("model", "Modelled outputs", "Produced by OmniGrid. Estimates, never measurements."),
        (
            "validation",
            "Validation sources",
            "Deliberately held out of the model so they can test it. Never inputs.",
        ),
        ("basemap", "Basemap", "Cartographic only."),
    ]
    out = [
        "# Data sources",
        "",
        "<!-- GENERATED from pipeline/sources/registry.yaml by pipeline/manifest.py.",
        "     Do not edit by hand: regenerate with `make attribution`. -->",
        "",
        "Every figure in OmniGrid is traceable to an entry below. Values are tagged",
        "**measured** (reported by a source), **derived** (computed from sources by a",
        "named formula) or **modelled** (output of the supply-shed model).",
        "",
    ]
    for role, heading, blurb in roles:
        srcs = [s for s in reg.by_role(role) if used is None or s.id in used]
        if not srcs:
            continue
        out += [f"## {heading}", "", blurb, ""]
        for s in sorted(srcs, key=lambda x: x.name):
            out.append(f"### {s.name}")
            out.append("")
            out.append(f"- **Publisher** — {s.publisher}")
            if s.version:
                out.append(f"- **Version** — {s.version}")
            out.append(f"- **Licence** — [{s.licence}]({s.licence_url})")
            out.append(f"- **Source** — <{s.url}>")
            out.append(f"- **Attribution** — {s.attribution}")
            if s.is_vendored:
                out.append(
                    "- **Access** — behind a name/email form; vendored into "
                    "`data/raw/gem/` by hand and checksummed"
                )
            if s.blocking_issue:
                out.append("")
                out.append("> [!WARNING]")
                out.append("> " + " ".join(s.blocking_issue.split()))
            elif s.notes:
                out.append("")
                out.append("> " + " ".join(s.notes.split()))
            out.append("")
    return "\n".join(out)


def write_attribution(reg: Registry, used: set[str] | None = None) -> Path:
    out = ROOT / "DATA_SOURCES.md"
    out.write_text(render_data_sources_md(reg, used))
    return out


def check(reg: Registry, used: set[str]) -> list[str]:
    """Build-gate checks. Returns problems; a non-empty list must fail the build."""
    problems: list[str] = []
    unknown = sorted(used - reg.sources.keys())
    if unknown:
        problems.append(f"cited but unregistered: {', '.join(unknown)}")
    for s in reg.resolve(used & reg.sources.keys()):
        if s.is_blocked:
            problems.append(
                f"{s.id}: used despite an unresolved licence ({s.licence}). "
                f"{' '.join((s.blocking_issue or '').split())}"
            )
    # Attribution must cover exactly what was used.
    lines = reg.attribution_lines(used & reg.sources.keys())
    for s in reg.resolve(used & reg.sources.keys()):
        if s.attribution not in lines:
            problems.append(f"{s.id}: used but missing from generated attribution")
    return problems


if __name__ == "__main__":
    reg = load()
    path = write_attribution(reg)
    print(f"wrote {path.relative_to(ROOT)} ({len(reg.sources)} sources)")
