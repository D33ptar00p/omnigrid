"""Per-field provenance.

Every substantive value in OmniGrid carries where it came from and what kind of
claim it is. Datasets disagree -- GEM and WRI report different capacities for the
same plant -- so "which source said this" is real information, not bookkeeping.

Three kinds of claim, and the distinction is load-bearing:

    MEASURED  reported by a named source; cite the source
    DERIVED   computed from cited sources by a named formula; cite both
    MODELLED  output of the supply-shed model; cite its assumptions

The UI renders these differently so a reader can tell a measurement from an
estimate at a glance. A number whose kind is wrong is worse than a missing one.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Generic, TypeVar


class Kind(str, Enum):
    MEASURED = "measured"
    DERIVED = "derived"
    MODELLED = "modelled"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Cited(Generic[T]):
    """A value bound to its provenance. Immutable on purpose: a value and its
    citation must not be able to drift apart."""

    value: T
    kind: Kind
    source_id: str
    #: For DERIVED/MODELLED: the formula or method identifier, resolvable to an
    #: anchor on the methodology page.
    method: str | None = None
    #: Other source_ids that fed a derivation (e.g. Ember for calibration).
    via: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("Cited value has no source_id")
        if self.kind in (Kind.DERIVED, Kind.MODELLED) and not self.method:
            raise ValueError(
                f"{self.kind.value} value from {self.source_id!r} has no method; "
                "derived and modelled values must name the formula that produced them"
            )

    def to_json(self) -> dict[str, Any]:
        v = self.value.value if isinstance(self.value, Enum) else self.value
        out: dict[str, Any] = {"v": v, "k": self.kind.value, "s": self.source_id}
        if self.method:
            out["m"] = self.method
        if self.via:
            out["via"] = list(self.via)
        return out


def measured(value: T, source_id: str) -> Cited[T]:
    return Cited(value, Kind.MEASURED, source_id)


def derived(value: T, method: str, source_id: str, *via: str) -> Cited[T]:
    return Cited(value, Kind.DERIVED, source_id, method, tuple(via))


def modelled(value: T, method: str, *via: str) -> Cited[T]:
    return Cited(value, Kind.MODELLED, "omnigrid_model", method, tuple(via))


def collect_source_ids(obj: Any) -> set[str]:
    """Walk a structure and gather every source_id actually cited.

    This is what the build compares against the registry, in both directions:
    nothing cited may be unregistered, and nothing registered as used may be
    missing from the generated attribution.

    Descends only into containers and dataclasses. Walking arbitrary ``__dict__``
    would be shorter but wrong -- enum members expose a ``__dict__`` that leads
    back to the enum class, its methods, and round to the members again, so the
    walk never terminates. An id-based visited set backs that up against any other
    cycle (shared or self-referential structures).
    """
    found: set[str] = set()
    seen: set[int] = set()
    stack: list[Any] = [obj]
    while stack:
        cur = stack.pop()
        if cur is None or isinstance(cur, (str, bytes, int, float, bool, Enum)):
            continue
        if (key := id(cur)) in seen:
            continue
        seen.add(key)

        if isinstance(cur, Cited):
            found.add(cur.source_id)
            found.update(cur.via)
            # A Cited may wrap a structure that itself carries citations.
            stack.append(cur.value)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple, set, frozenset)):
            stack.extend(cur)
        elif is_dataclass(cur) and not isinstance(cur, type):
            stack.extend(getattr(cur, f.name) for f in fields(cur) if hasattr(cur, f.name))
    return found
