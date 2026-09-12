"""Citation integrity: the build must not be able to produce an uncited number.

These tests exist because attribution rots silently. A source gets swapped, a
field gets added, and the panel keeps claiming something that is no longer true.
Generating attribution and checking usage from one registry is what prevents that,
and these assertions are what keep the generation honest.
"""

from __future__ import annotations

import pytest

from pipeline.provenance import Cited, Kind, collect_source_ids, derived, measured, modelled
from pipeline.sources.registry import ATTRIBUTION_REQUIRED, RegistryError, load


@pytest.fixture(scope="module")
def registry():
    return load()


# ---- registry wellformedness ----------------------------------------------


def test_registry_loads_and_validates(registry):
    assert registry.sources, "registry is empty"


def test_every_source_has_attribution_and_licence(registry):
    for s in registry.sources.values():
        assert s.attribution.strip(), f"{s.id} has no attribution string"
        assert s.licence.strip(), f"{s.id} has no licence"
        assert s.licence_url.strip(), f"{s.id} has no licence URL"


def test_attribution_required_licences_carry_real_attribution(registry):
    """ODbL and CC BY both oblige us to attribute. This is a licence condition."""
    for s in registry.sources.values():
        if s.licence in ATTRIBUTION_REQUIRED:
            assert len(s.attribution) > 10, f"{s.id}: attribution too thin for {s.licence}"


def test_validation_sources_are_not_model_inputs(registry):
    """Held-out data must stay held out, or the validation proves nothing."""
    for s in registry.by_role("validation"):
        assert s.role == "validation"
        assert s.id not in {x.id for x in registry.by_role("input")}


def test_unresolved_licences_are_flagged_not_silently_used(registry):
    """A source whose licence we haven't established must announce itself."""
    for s in registry.sources.values():
        if s.licence == "UNRESOLVED":
            assert s.is_blocked
            assert s.blocking_issue, f"{s.id} is UNRESOLVED but explains nothing"


def test_unknown_source_id_is_fatal(registry):
    with pytest.raises(RegistryError, match="unregistered source"):
        registry["not_a_real_source"]


def test_resolve_reports_all_unknown_ids_at_once(registry):
    with pytest.raises(RegistryError) as ei:
        registry.resolve({"gem_gipt", "bogus_a", "bogus_b"})
    assert "bogus_a" in str(ei.value) and "bogus_b" in str(ei.value)


# ---- provenance values ------------------------------------------------------


def test_measured_value_carries_its_source():
    c = measured(3906.0, "gem_gipt")
    assert c.kind is Kind.MEASURED and c.source_id == "gem_gipt"


def test_derived_and_modelled_must_name_a_method():
    """An estimate without a stated formula is an unfalsifiable claim."""
    with pytest.raises(ValueError, match="no method"):
        Cited(1.0, Kind.DERIVED, "gem_gipt")
    with pytest.raises(ValueError, match="no method"):
        Cited(1.0, Kind.MODELLED, "omnigrid_model")


def test_value_without_source_is_rejected():
    with pytest.raises(ValueError, match="no source_id"):
        Cited(1.0, Kind.MEASURED, "")


def test_cited_is_immutable():
    """A value and its citation must not be able to drift apart."""
    c = measured(1.0, "gem_gipt")
    with pytest.raises(Exception):
        c.value = 2.0  # type: ignore[misc]


def test_collect_walks_nested_structures():
    blob = {
        "capacity": measured(3906.0, "gem_gipt"),
        "rows": [derived(18000.0, "generation.cf", "gem_gipt", "ember_yearly")],
        "shed": {"pop": modelled(4.1e6, "shed.population_served", "kontur_pop")},
    }
    assert collect_source_ids(blob) == {
        "gem_gipt", "ember_yearly", "omnigrid_model", "kontur_pop",
    }


def test_every_cited_source_resolves_against_the_registry(registry):
    """The join that matters: nothing may cite a source the registry doesn't know."""
    blob = {
        "capacity": measured(3906.0, "gem_gipt"),
        "generation": derived(18000.0, "generation.cf", "gem_gipt", "ember_yearly"),
        "population_served": modelled(4.1e6, "shed.population_served", "kontur_pop"),
    }
    resolved = registry.resolve(collect_source_ids(blob))
    assert {s.id for s in resolved} >= {"gem_gipt", "ember_yearly", "omnigrid_model"}


def test_attribution_covers_exactly_the_sources_used(registry):
    """Attribution is generated from usage, so it can neither over- nor under-claim."""
    used = {"gem_gipt", "gridfinder", "ember_yearly"}
    lines = registry.attribution_lines(used)
    assert len(lines) == len(used)
    for sid in used:
        assert registry[sid].attribution in lines
    # and nothing else leaked in
    unused = registry["hifld_territories"].attribution
    assert unused not in lines


# ---- walk safety ------------------------------------------------------------


def test_walk_terminates_on_enum_values():
    """Regression: enum members expose a __dict__ that cycles back to the enum
    class and its methods. A generic __dict__ walk never terminates on them."""
    from pipeline.schema import Asset, AssetKind, Fuel, Status

    asset = Asset(
        id="x", kind=AssetKind.GENERATION, name="n", country="GBR", lat=0.0, lon=0.0,
        fuel=measured(Fuel.COAL, "wri_gppd"),
        status=measured(Status.OPERATING, "wri_gppd"),
    )
    assert collect_source_ids([asset]) == {"wri_gppd"}


def test_walk_survives_self_referential_structures():
    blob: dict = {"cap": measured(1.0, "gem_gipt")}
    blob["self"] = blob
    assert collect_source_ids(blob) == {"gem_gipt"}


def test_walk_descends_into_cited_containers():
    """A Cited may wrap a structure that itself carries citations."""
    nested = measured([measured(1.0, "ember_yearly")], "gem_gipt")
    assert collect_source_ids(nested) == {"gem_gipt", "ember_yearly"}


def test_enum_values_serialise_to_their_string():
    from pipeline.schema import Fuel

    assert measured(Fuel.COAL, "wri_gppd").to_json()["v"] == "coal"
