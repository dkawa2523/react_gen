"""Public evidence access cannot invalidate a catalog's physical-target indexes."""

from dataclasses import FrozenInstanceError, replace

import pytest

from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.model import ReactionCandidate, Term
from reactgen.records import NumericDataset, Property, ReactionRecord, StateRecord


def test_catalog_membership_cannot_be_reassigned() -> None:
    target = candidate_state({"Ar": 1}, 0)
    catalog = EvidenceCatalog((StateRecord("argon", target),))
    with pytest.raises(FrozenInstanceError):
        catalog.state_records = ()  # type: ignore[misc]
    assert catalog.state(target).match == "exact"
    assert len(catalog.state_records) == 1
    assert EvidenceCatalog().state(target).match == "none"


def test_mutating_input_or_returned_state_does_not_change_the_snapshot() -> None:
    target = candidate_state({"Ar": 1}, 0)
    record = StateRecord("argon", target, {"mass_amu": Property(40, "amu")})
    catalog = EvidenceCatalog((record,))
    record.candidate.composition.clear()
    record.properties.clear()
    lookup_target = candidate_state({"Ar": 1}, 0)
    first = catalog.state(lookup_target)
    assert first.match == "exact"
    assert first.preferred is not None
    first.preferred.candidate.composition.clear()
    first.preferred.properties.clear()
    catalog.state_records[0].properties.clear()
    second = catalog.state(lookup_target)
    assert second.match == "exact"
    assert second.preferred is not None
    assert second.preferred.value("mass_amu") == 40
    assert second.preferred.candidate.composition == {"Ar": 1}


def test_mutating_exposed_reaction_and_datasets_does_not_change_the_snapshot() -> None:
    target = candidate_state({"Ar": 1}, 0)
    reaction = ReactionCandidate(
        "elastic",
        (Term("e"), Term(target.id)),
        (Term("e"), Term(target.id)),
        "electron",
        "elastic",
        "mechanical",
        "elastic",
        1,
    )
    dataset = NumericDataset("table", "rate_coefficient", "constant", params={"value": 2})
    record = ReactionRecord("elastic", reaction.equation_key, "electron", "elastic", (target,))
    offered = {reaction.id: (dataset,)}
    catalog = EvidenceCatalog(reaction_records=(record,), overlay_datasets=offered)
    offered.clear()
    dataset.params["value"] = 9
    catalog.reaction_records[0].states[0].composition.clear()
    catalog.overlay_datasets.clear()
    first = catalog.reaction(reaction)
    first.overlay_datasets[0].params["value"] = 11
    first.records[0].states[0].composition.clear()
    second = catalog.reaction(reaction)
    assert second.overlay_datasets[0].params["value"] == 2
    assert second.records[0].states[0].composition == {"Ar": 1}


def test_new_catalog_is_the_explicit_evidence_update() -> None:
    target = candidate_state({"Ar": 1}, 0)
    original = EvidenceCatalog((StateRecord("argon", target),))
    changed = EvidenceCatalog((*original.state_records, StateRecord("second", target)))
    assert len(original.state(target).records) == 1
    assert len(changed.state(target).records) == 2
    unchanged = replace(original)
    removed = replace(original, state_records=())
    assert unchanged.state(target).match == "exact"
    assert removed.state(target).match == "none"
    assert original.state(target).match == "exact"
    assert unchanged.fingerprint == original.fingerprint
    assert removed.fingerprint != original.fingerprint
    assert changed.fingerprint != original.fingerprint


def test_fingerprint_covers_manual_values_and_is_independent_of_input_order() -> None:
    target = candidate_state({"Ar": 1}, 0)
    first = StateRecord("first", target, {"mass_amu": Property(40, "amu")})
    second = StateRecord("second", target, {"mass_amu": Property(41, "amu")})
    assert EvidenceCatalog((first,)).fingerprint != EvidenceCatalog().fingerprint
    assert EvidenceCatalog((first,)).fingerprint != EvidenceCatalog((second,)).fingerprint
    assert (
        EvidenceCatalog((first, second)).fingerprint == EvidenceCatalog((second, first)).fingerprint
    )
