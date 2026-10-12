"""Malformed scope input must not obtain unscoped legacy qualification."""

import pytest

from reactgen.chemistry import parse_state_id
from reactgen.evidence import snapshot_reaction
from reactgen.records import (
    NumericDataset,
    Property,
    ReactionRecord,
    RegistryState,
    StateRecord,
    Thermo,
    normalized_dataset,
    normalized_property,
    normalized_state_record,
    normalized_thermo,
    review_scope,
)

FIT = {
    "low": [2.5, 0, 0, 0, 0, 0, 0],
    "high": [2.5, 0, 0, 0, 0, 0, 0],
    "t_min": 200,
    "t_mid": 1000,
    "t_max": 2000,
    "tier": "reviewed",
}


def _direct_constructors(raw):
    state = parse_state_id("Ar@ground")
    assert state is not None
    return (
        lambda: Property(1, "eV", tier="reviewed", review_scope=raw),
        lambda: Thermo(
            tuple(FIT["low"]),
            tuple(FIT["high"]),
            200,
            1000,
            2000,
            tier="reviewed",
            review_scope=raw,
        ),
        lambda: RegistryState(review_scope=raw),
        lambda: StateRecord("state", state, tier="reviewed", review_scope=raw),
        lambda: NumericDataset(
            "number", "rate_coefficient", "constant", tier="reviewed", review_scope=raw
        ),
        lambda: ReactionRecord(
            "reaction",
            (None, None, ((state.id, 2),), ((state.id, 2),)),
            "neutral",
            "elastic",
            (state,),
            tier="reviewed",
            review_scope=raw,
        ),
    )


@pytest.mark.parametrize("raw", [False, 0, "", {}])
def test_falsey_malformed_scopes_are_rejected_by_external_adapters(raw) -> None:
    state = parse_state_id("Ar@ground")
    assert state is not None
    adapters = (
        lambda: review_scope({"review_scope": raw}),
        lambda: normalized_property({"value": 1, "tier": "reviewed", "review_scope": raw}),
        lambda: normalized_thermo(FIT | {"review_scope": raw}),
        lambda: normalized_state_record({"species": state.id, "review_scope": raw}, state),
        lambda: normalized_dataset({"id": "number", "review_scope": raw}),
        lambda: snapshot_reaction(
            {"reaction": "Ar + Ar -> Ar + Ar", "type": "elastic", "review_scope": raw}
        ),
    )
    for normalize in adapters:
        with pytest.raises(ValueError, match="review_scope must be a list"):
            normalize()


@pytest.mark.parametrize("raw", [False, 0, "", {}])
def test_direct_record_construction_cannot_bypass_scope_validation(raw) -> None:
    for construct in _direct_constructors(raw):
        with pytest.raises(ValueError, match="review_scope must be a list"):
            construct()


@pytest.mark.parametrize("raw", [None, [], ()])
def test_empty_scope_preserves_the_explicit_legacy_qualification_boundary(raw) -> None:
    assert review_scope({}) == ()
    assert review_scope({"review_scope": raw}) == ()
    for construct in _direct_constructors(raw):
        assert construct().review_scope == ()


def test_unknown_scope_names_are_retained_without_qualifying_existing_claims() -> None:
    scopes = ["future_quantity", "future_quantity"]
    records = [construct() for construct in _direct_constructors(scopes)]
    assert all(record.review_scope == ("future_quantity",) for record in records)
    prop, thermo, _, state, numeric, reaction = records
    assert not prop.reviewed_for("ionization_energy_eV")
    assert not thermo.reviewed_for("thermochemical_model")
    assert not state.reviewed
    assert not numeric.reviewed
    assert not reaction.reviewed_for("channel_assertion")
