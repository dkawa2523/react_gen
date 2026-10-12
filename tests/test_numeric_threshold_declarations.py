"""A cross-section table checks only compatible, qualified energy declarations."""

from dataclasses import replace

import pytest

from reactgen.case import Conditions
from reactgen.evidence import ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import assess_dataset
from reactgen.records import (
    Property,
    ReactionRecord,
    Uncertainty,
    normalized_dataset,
    qualified_channel_energy,
)
from reactgen.units import JOULE_PER_EV

REACTION = ReactionCandidate(
    "ionization",
    (Term("e"), Term("Ar@ground")),
    (Term("e", 2), Term("Ar+@ground")),
    "electron",
    "ionization",
    "test",
    "test",
    0,
)


def declaration(prop: Property, identifier: str = "energy-source") -> ReactionRecord:
    return ReactionRecord(
        identifier,
        REACTION.equation_key,
        "electron",
        "ionization",
        (),
        energy_properties={"threshold_eV": prop},
    )


def check(tmp_path, *records: ReactionRecord, related: tuple[ReactionRecord, ...] = ()):
    path = tmp_path / "cross_section.csv"
    path.write_text("energy_eV,sigma_m2\n8,1e-20\n12,2e-20\n", encoding="utf-8")
    dataset = normalized_dataset(
        {
            "id": "curve",
            "kind": "cross_section",
            "form": "table",
            "unit": "m2",
            "observable": "ionization",
            "independent_variable": "electron_energy",
            "parameter_units": {"x": "eV"},
            "asset": {"path": path.name},
            "validity": {"quantity": "electron_energy", "minimum": 8, "maximum": 12, "unit": "eV"},
            "status": "reviewed",
        },
        base=tmp_path,
    )
    return assess_dataset(
        dataset, REACTION, ReactionEvidence(tuple(records), related), Conditions()
    )


def threshold(**changes) -> Property:
    return replace(Property(10, "eV", tier="reviewed", definition="channel_threshold"), **changes)


def test_parent_review_cannot_qualify_an_imported_energy(tmp_path) -> None:
    record = replace(declaration(threshold(tier="imported")), tier="reviewed", status="reviewed")
    assert check(tmp_path, record).status == "needs_input"
    # Its inverse is allowed: independent energy review needs no channel tier.
    independent = declaration(threshold())
    result = check(tmp_path, independent)
    assert result.status == "invalid"
    assert "nominal declared" in result.reason
    assert "not a measured absolute limit" in result.reason


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_parent_declaration_stop_applies_to_its_independently_reviewed_energy(
    tmp_path, status
) -> None:
    record = replace(declaration(threshold()), status=status, review_scope=("channel_assertion",))
    assert qualified_channel_energy(record, "threshold_eV") is None
    assert check(tmp_path, record).status == "needs_input"


@pytest.mark.parametrize("status", ["imported", "reviewed"])
def test_parent_tier_and_channel_scope_do_not_restrict_independent_energy(tmp_path, status) -> None:
    record = replace(
        declaration(threshold(review_scope=("threshold_eV",))),
        tier="imported",
        status=status,
        review_scope=("channel_assertion",),
    )
    assert qualified_channel_energy(record, "threshold_eV") is not None
    assert check(tmp_path, record).status == "invalid"


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_same_record_parent_stop_is_not_hidden_by_unchanged_energy_property(
    tmp_path, status
) -> None:
    first = declaration(threshold())
    stopped = replace(first, status=status)
    for records in ((first, stopped), (stopped, first)):
        assert check(tmp_path, *records).status == "needs_input"


def test_rejected_independent_record_does_not_suppress_an_accepted_source(tmp_path) -> None:
    first = declaration(threshold())
    stopped = replace(declaration(threshold(value=15), "other-source"), status="rejected")
    assert check(tmp_path, first, stopped).status == "invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"definition": "appearance_energy"},
        {"qualifier": "upper_limit"},
        {"review_scope": ("channel_assertion",)},
        {"status": "rejected"},
    ],
)
def test_different_observable_or_unqualified_declaration_does_not_reject_the_curve(
    tmp_path, changes
) -> None:
    assert check(tmp_path, declaration(threshold(**changes))).status == "needs_input"


def test_legacy_unspecified_threshold_keeps_only_nominal_declaration_comparison(tmp_path) -> None:
    result = check(tmp_path, declaration(threshold(definition=None)))
    assert result.status == "invalid"
    assert "nominal declared" in result.reason


def test_uncertainty_uses_the_conservative_lower_interval_bound(tmp_path) -> None:
    assert (
        check(tmp_path, declaration(threshold(uncertainty=Uncertainty(absolute=3)))).status
        == "needs_input"
    )
    result = check(tmp_path, declaration(threshold(uncertainty=Uncertainty(absolute=1))))
    assert result.status == "invalid"
    assert "lower bound" in result.reason


def test_energy_and_uncertainty_convert_together(tmp_path) -> None:
    record = declaration(
        threshold(
            value=10 * JOULE_PER_EV,
            unit="J",
            uncertainty=Uncertainty(absolute=3 * JOULE_PER_EV),
        )
    )
    assert check(tmp_path, record).status == "needs_input"


@pytest.mark.parametrize(
    "uncertainty",
    [Uncertainty(factor=0), Uncertainty(absolute=-1), Uncertainty(note="not quantified")],
)
def test_invalid_or_unquantified_interval_is_not_replaced_with_a_nominal_limit(
    tmp_path, uncertainty
) -> None:
    assert check(tmp_path, declaration(threshold(uncertainty=uncertainty))).status == "needs_input"


def test_conflicting_values_do_not_supply_a_threshold_limit(tmp_path) -> None:
    first = declaration(threshold())
    second = declaration(threshold(value=11), "other-source")
    for records in ((first, second), (second, first)):
        assert check(tmp_path, *records).status == "needs_input"


def test_conversion_roundoff_is_distinct_from_a_same_unit_value_change(tmp_path) -> None:
    first = declaration(threshold())
    converted = declaration(threshold(value=10 * JOULE_PER_EV, unit="J"), "converted-source")
    assert check(tmp_path, first, converted).status == "invalid"
    changed = declaration(threshold(value=10 + 1e-13), "changed-source")
    assert check(tmp_path, first, changed).status == "needs_input"


def test_same_source_id_energy_unit_copy_is_not_a_conflict(tmp_path) -> None:
    first = declaration(threshold(uncertainty=Uncertainty(absolute=1)))
    copy = replace(
        first,
        energy_properties={
            "threshold_eV": threshold(
                value=10 * JOULE_PER_EV,
                unit="J",
                uncertainty=Uncertainty(absolute=JOULE_PER_EV),
            )
        },
    )
    for records in ((first, copy), (copy, first)):
        assert check(tmp_path, *records).status == "invalid"


def test_same_source_id_uncertainty_conflict_is_not_merged_into_a_limit(tmp_path) -> None:
    first = declaration(threshold(uncertainty=Uncertainty(absolute=1)))
    changed = replace(
        first, energy_properties={"threshold_eV": threshold(uncertainty=Uncertainty(absolute=0.5))}
    )
    assert check(tmp_path, first, changed).status == "needs_input"


def test_other_quantity_conflict_does_not_remove_threshold_comparison(tmp_path) -> None:
    first = declaration(threshold())
    changed = replace(
        first,
        energy_properties=first.energy_properties
        | {
            "delta_e_eV": Property(100, "eV", tier="reviewed"),
        },
    )
    assert check(tmp_path, first, changed).status == "invalid"


@pytest.mark.parametrize("same_id", [False, True])
def test_explicit_threshold_conflict_does_not_supply_a_limit(tmp_path, same_id) -> None:
    first = declaration(threshold())
    conflicting = declaration(
        threshold(status="conflicting"), first.id if same_id else "other-source"
    )
    assert check(tmp_path, first, conflicting).status == "needs_input"


def test_related_channel_conflict_requires_the_same_source_record_id(tmp_path) -> None:
    first = declaration(threshold())
    collision = replace(first, process="dissociation")
    assert check(tmp_path, first, related=(collision,)).status == "needs_input"
    unrelated = replace(collision, id="different-source")
    assert check(tmp_path, first, related=(unrelated,)).status == "invalid"
