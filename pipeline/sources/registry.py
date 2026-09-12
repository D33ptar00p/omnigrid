"""Load and enforce the source registry.

The registry is the single source of truth for provenance. The attribution panel,
the methodology reference list, DATA_SOURCES.md and manifest.json are all generated
from it, which is what stops attribution drifting away from what was actually used.

Enforcement lives here rather than in a linter because it has to fail the build.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")

REQUIRED_FIELDS = (
    "name", "short", "publisher", "url", "licence", "licence_url",
    "attribution", "access", "role",
)
VALID_ACCESS = {"direct", "form", "derived"}
VALID_ROLES = {"input", "validation", "basemap", "model"}

#: Licences that oblige us to attribute. Both of the ones we actually rely on do;
#: the test that every used source appears in generated attribution is not
#: optional politeness, it is the licence condition.
ATTRIBUTION_REQUIRED = {"CC-BY-4.0", "ODbL-1.0", "CC0-1.0", "entsoe-terms"}


class RegistryError(Exception):
    """Raised when the registry is malformed or a citation cannot be resolved.

    Always fatal: a build that cannot prove where its numbers came from must not
    produce output.
    """


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    name: str
    short: str
    publisher: str
    url: str
    licence: str
    licence_url: str
    attribution: str
    access: str
    role: str
    version: str | None = None
    download_url: str | None = None
    notes: str | None = None
    blocking_issue: str | None = None
    provides: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    raw_glob: str | None = None

    @property
    def is_vendored(self) -> bool:
        """True if a human must fetch this by hand (GEM's email-form downloads)."""
        return self.access == "form"

    @property
    def is_blocked(self) -> bool:
        return self.licence == "UNRESOLVED" or self.blocking_issue is not None

    def citation(self, accessed: str | None = None) -> str:
        bits = [self.attribution]
        if self.version and self.version not in self.attribution:
            bits.append(f"Version {self.version}.")
        bits.append(f"Licence: {self.licence} <{self.licence_url}>.")
        bits.append(f"<{self.url}>")
        if accessed:
            bits.append(f"Accessed {accessed}.")
        return " ".join(bits)


@dataclass
class Registry:
    sources: dict[str, Source] = field(default_factory=dict)

    def __getitem__(self, source_id: str) -> Source:
        try:
            return self.sources[source_id]
        except KeyError:
            raise RegistryError(
                f"citation names unregistered source {source_id!r}; "
                f"add it to {REGISTRY_PATH.name} before using it"
            ) from None

    def __contains__(self, source_id: str) -> bool:
        return source_id in self.sources

    def by_role(self, role: str) -> list[Source]:
        return [s for s in self.sources.values() if s.role == role]

    @property
    def blocked(self) -> list[Source]:
        return [s for s in self.sources.values() if s.is_blocked]

    @property
    def vendored(self) -> list[Source]:
        return [s for s in self.sources.values() if s.is_vendored]

    def resolve(self, source_ids: set[str]) -> list[Source]:
        """Resolve cited ids to sources, failing loudly on any that is unregistered."""
        unknown = sorted(source_ids - self.sources.keys())
        if unknown:
            raise RegistryError(
                f"{len(unknown)} cited source(s) not in the registry: {', '.join(unknown)}"
            )
        return [self.sources[i] for i in sorted(source_ids)]

    def attribution_lines(self, source_ids: set[str] | None = None) -> list[str]:
        """Attribution text for the sources actually used.

        Generated from the same registry the pipeline reads, so the panel cannot
        claim a source we didn't use, or omit one we did.
        """
        chosen = self.resolve(source_ids) if source_ids is not None else sorted(
            self.sources.values(), key=lambda s: s.id
        )
        return [s.attribution for s in chosen]


def _validate(raw: dict[str, Any]) -> None:
    if raw.get("schema_version") != 1:
        raise RegistryError(f"unsupported registry schema_version {raw.get('schema_version')!r}")
    srcs = raw.get("sources")
    if not isinstance(srcs, dict) or not srcs:
        raise RegistryError("registry has no sources")
    for sid, s in srcs.items():
        missing = [f for f in REQUIRED_FIELDS if not s.get(f)]
        if missing:
            raise RegistryError(f"source {sid!r} missing required field(s): {', '.join(missing)}")
        if s["access"] not in VALID_ACCESS:
            raise RegistryError(f"source {sid!r} has invalid access {s['access']!r}")
        if s["role"] not in VALID_ROLES:
            raise RegistryError(f"source {sid!r} has invalid role {s['role']!r}")
        if s["licence"] in ATTRIBUTION_REQUIRED and not s.get("attribution", "").strip():
            raise RegistryError(
                f"source {sid!r} is {s['licence']} which requires attribution, "
                "but its attribution string is empty"
            )


@lru_cache(maxsize=1)
def load(path: Path = REGISTRY_PATH) -> Registry:
    raw = yaml.safe_load(path.read_text())
    _validate(raw)
    sources = {}
    for sid, s in raw["sources"].items():
        sources[sid] = Source(
            id=sid,
            name=s["name"],
            short=s["short"],
            publisher=s["publisher"],
            url=s["url"],
            licence=s["licence"],
            licence_url=s["licence_url"],
            attribution=s["attribution"],
            access=s["access"],
            role=s["role"],
            version=s.get("version"),
            download_url=s.get("download_url"),
            notes=s.get("notes"),
            blocking_issue=s.get("blocking_issue"),
            provides=tuple(s.get("provides", ())),
            files=tuple(s.get("files", ())),
            raw_glob=s.get("raw_glob"),
        )
    return Registry(sources)


def sha256(path: Path, _chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(_chunk):
            h.update(block)
    return h.hexdigest()
