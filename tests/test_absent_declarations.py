"""Missing assertions and empty placeholders are distinct from unreviewed evidence."""

from dataclasses import asdict, replace

import pytest

from reactgen import outcomes
from reactgen.assessment import assess_state, evaluate
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, StateEvidence
from reactgen.model import CandidateSet
from reactgen.records import FormationReference, Property, StateRecord


def claim(*records):
    state = records[0].candidate
    return assess_state(
        state, StateEvidence("exact", tuple(records)), CandidateSet(states={state.id: state})
    )


def label(result):
    return outcomes.assessment_outcome(asdict(result), {})


@pytest.mark.parametrize("tier", ["imported", "derived", "reviewed", "curated"])
@pytest.mark.parametrize("status", ["imported", "conflicting"])
def test_property_record_qualification_is_not_a_missing_existence_assertion_review(tier, status):
    state = candidate_state({"H": 2, "O": 1}, 0)
    record = StateRecord(
        state.id,
        state,
        tier=tier,
        status=status,
        properties={
            "enthalpy_formation_eV": Property(
                1.0,
                "eV",
                tier="reviewed",
                formation_reference=FormationReference(298.15, "standard_elements", 100000),
            )
        },
    )
    result = claim(record)
    assert result.verdict == "unknown"
    assert {item.responsibility for item in result.requirements} == {"source_information"}
    assert label(result) == {"label": "data_missing", "blocking_causes": ["data_missing"]}


@pytest.mark.parametrize("existence", ["unknown", "hypothetical", "transient"])
def test_lifetime_and_unresolved_labels_need_existence_data(existence):
    state = candidate_state({"Ar": 1}, 0)
    result = claim(
        StateRecord(
            state.id,
            state,
            existence=existence,
            existence_source="annotation source",
            tier="reviewed",
            lifetime_s=1e-8,
        )
    )
    assert result.verdict == "unknown"
    assert {item.responsibility for item in result.requirements} == {"source_information"}


@pytest.mark.parametrize("existence", ["confirmed", "unbound"])
def test_a_supplied_unreviewed_existence_assertion_keeps_its_review_work(existence):
    state = candidate_state({"Ar": 1}, 0)
    result = claim(StateRecord(state.id, state, existence=existence, existence_source="source"))
    assert result.verdict == "unknown"
    assert label(result) == {"label": "review_required", "blocking_causes": ["review_required"]}


def test_missing_source_and_missing_assertion_review_can_coexist():
    state = candidate_state({"Ar": 1}, 0)
    result = claim(StateRecord(state.id, state, existence="confirmed"))
    assert result.verdict == "unknown"
    assert {item.responsibility for item in result.requirements} == {
        "source_information",
        "source_review",
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_reviewed_exclusion_precedes_property_only_information_and_metadata_conflict(reverse):
    state = candidate_state({"Ar": 1}, 0)
    excluded = StateRecord(
        "exclusion",
        state,
        existence="unbound",
        existence_source="negative assertion",
        tier="reviewed",
    )
    quantities = StateRecord(
        "properties",
        state,
        tier="curated",
        status="conflicting",
        properties={"enthalpy_formation_eV": Property(None, "eV")},
    )
    ordered = (quantities, excluded) if reverse else (excluded, quantities)
    result = claim(*ordered)
    assert result.verdict == "fail"
    assert result.requirements == ()
    assert result.basis == ("snapshot:exclusion",)
    assert label(result) == {"label": "not_satisfied", "blocking_causes": []}


def test_reviewed_opposite_assertions_are_a_review_conflict_not_missing_data():
    state = candidate_state({"Ar": 1}, 0)
    excluded = StateRecord(
        "exclusion",
        state,
        existence="unbound",
        existence_source="negative assertion",
        tier="reviewed",
    )
    supported = replace(excluded, id="support", existence="confirmed", existence_source="positive")
    result = claim(excluded, supported)
    assert result.verdict == "unknown"
    assert label(result) == {"label": "review_required", "blocking_causes": ["review_required"]}


@pytest.mark.parametrize("tier", ["imported", "reviewed"])
def test_empty_affinity_placeholder_is_a_missing_value_not_an_assertion(tier):
    neutral, anion = (candidate_state({"Ar": 1}, charge) for charge in (0, -1))
    record = StateRecord(
        neutral.id, neutral, properties={"electron_affinity_eV": Property(None, "eV", tier=tier)}
    )
    result = evaluate(
        CandidateSet(states={neutral.id: neutral, anion.id: anion}),
        EvidenceCatalog(state_records=(record,)),
        Conditions(),
    ).state_assessments[anion.id]["state"]
    assert result.verdict == "unknown"
    assert result.proposition == "ground_anion_electron_binding"
    assert {item.responsibility for item in result.requirements} == {"source_information"}


@pytest.mark.parametrize(
    ("tier", "verdict", "cause"),
    [
        ("imported", "unknown", "review_required"),
        ("reviewed", "fail", "not_satisfied"),
    ],
)
def test_null_with_a_scientific_nonbinding_declaration_is_not_discarded(tier, verdict, cause):
    neutral, anion = (candidate_state({"Ar": 1}, charge) for charge in (0, -1))
    record = StateRecord(
        neutral.id,
        neutral,
        properties={"electron_affinity_eV": Property(None, "eV", qualifier="unbound", tier=tier)},
    )
    result = evaluate(
        CandidateSet(states={neutral.id: neutral, anion.id: anion}),
        EvidenceCatalog(state_records=(record,)),
        Conditions(),
    ).state_assessments[anion.id]["state"]
    assert result.verdict == verdict
    assert label(result)["label"] == cause
