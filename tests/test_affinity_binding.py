"""EA describes electron binding, independently of lifetime and other instability."""

from dataclasses import replace

import pytest

from reactgen.assessment import _preferred_state, assess_state, assess_thermochemistry
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import ReactionEvidence, StateEvidence
from reactgen.model import Assessment, CandidateSet, ReactionCandidate, Term
from reactgen.records import Property, StateRecord, Uncertainty
from reactgen.units import JOULE_PER_EV


def _binding(*properties: Property) -> tuple[Assessment, Assessment, dict[str, float]]:
    neutral, anion = (candidate_state({"Ar": 1}, charge) for charge in (0, -1))
    candidates = CandidateSet(states={state.id: state for state in (neutral, anion)})
    evidence = {
        neutral.id: StateEvidence(
            "exact",
            tuple(
                StateRecord(str(index), neutral, properties={"electron_affinity_eV": prop})
                for index, prop in enumerate(properties)
            ),
        )
    }
    reaction = ReactionCandidate(
        "attachment",
        (Term("e"), Term(neutral.id)),
        (Term(anion.id),),
        "electron",
        "attachment",
        "test",
        "test",
        0,
    )
    state = assess_state(anion, StateEvidence("none", ()), candidates, evidence)
    attachment, values = assess_thermochemistry(
        reaction, candidates, evidence, ReactionEvidence(), Conditions()
    )
    return state, attachment, values


@pytest.mark.parametrize("qualifier", ["upper limit", "lower limit", "approximate"])
def test_uninterpreted_affinity_qualifiers_cannot_assert_positive_electron_binding(
    qualifier: str,
) -> None:
    prop = Property(1.0, "eV", qualifier=qualifier, tier="reviewed")
    state, attachment, values = _binding(prop)
    assert state.verdict == attachment.verdict == "unknown"
    assert "electron_affinity_eV" not in values
    for judgment in (state, attachment):
        assert {(item.responsibility, item.quantity) for item in judgment.requirements} == {
            ("source_review", "electron_affinity_eV.qualifier"),
        }
    assert prop.qualifier == qualifier


@pytest.mark.parametrize("qualifier", [None, "unstable", "transient"])
def test_lifetime_and_other_instability_do_not_override_positive_electron_binding(
    qualifier: str | None,
) -> None:
    state, attachment, values = _binding(Property(1.0, "eV", qualifier=qualifier, tier="reviewed"))
    assert state.verdict == "pass"
    assert state.proposition == attachment.proposition == "ground_anion_electron_binding"
    assert attachment.verdict == "pass"
    assert "stabilization" in attachment.message
    assert values["electron_affinity_eV"] == 1.0


@pytest.mark.parametrize("qualifier", ["unstable", "transient"])
def test_lifetime_and_other_instability_alone_cannot_deny_electron_binding(qualifier: str) -> None:
    state, attachment, values = _binding(Property(qualifier=qualifier, tier="reviewed"))
    assert state.verdict == attachment.verdict == "unknown"
    assert "electron_affinity_eV" not in values


def test_equal_ea_with_different_lifetime_annotations_remains_nonconflicting() -> None:
    properties = tuple(
        Property(1.0, "eV", source=f"source-{index}", qualifier=qualifier, tier="reviewed")
        for index, qualifier in enumerate((None, "unstable", "transient"))
    )
    first, second = _binding(*properties), _binding(*reversed(properties))
    assert first == second
    assert first[0].verdict == "pass"
    assert first[1].verdict == "pass"
    assert first[2]["electron_affinity_eV"] == 1.0
    assert set(first[0].basis) == {"source-0", "source-1", "source-2"}


@pytest.mark.parametrize(("unit", "scale"), [("eV", 1.0), ("J", JOULE_PER_EV)])
def test_positive_ea_and_explicit_nonbinding_are_a_conflict_in_every_supported_unit(
    unit: str,
    scale: float,
) -> None:
    state, attachment, values = _binding(
        Property(1.0 * scale, unit, qualifier="unbound", tier="reviewed")
    )
    assert state.verdict == attachment.verdict == "unknown"
    assert "conflict" in state.message
    assert "conflict" in attachment.message
    assert "electron_affinity_eV" not in values


def test_positive_ea_and_separate_nonbinding_evidence_are_not_selected_by_input_order() -> None:
    positive = Property(1.0, "eV", source="binding", tier="reviewed")
    unbound = Property(qualifier="unbound", source="nonbinding", tier="reviewed")
    first, second = _binding(positive, unbound), _binding(unbound, positive)
    assert first == second
    assert first[0].verdict == first[1].verdict == "unknown"
    assert set(first[0].basis) == {"binding", "nonbinding"}
    assert "electron_affinity_eV" not in first[2]


@pytest.mark.parametrize("qualifier", ["unbound", " Unbound ", "UNBOUND", "\tunbound\n"])
@pytest.mark.parametrize("value", [None, -1.0, 1.0])
def test_known_ea_qualifier_spelling_has_one_scientific_meaning_and_retains_raw_text(
    qualifier: str,
    value: float | None,
) -> None:
    original = Property(value, "eV", qualifier=qualifier, source="first", tier="reviewed")
    equivalent = replace(original, qualifier="unbound", source="second")
    first, second = _binding(original, equivalent), _binding(equivalent, original)
    assert first == second
    assert first[0].verdict == first[1].verdict == ("unknown" if value == 1.0 else "fail")
    assert original.qualifier == qualifier
    assert equivalent.qualifier == "unbound"
    assert set(first[0].basis) == {"first", "second"}
    if value == 1.0:
        assert "electron_affinity_eV" not in first[2]


@pytest.mark.parametrize("value", [None, -1.0])
def test_consistent_reviewed_nonbinding_supports_only_the_electron_binding_exclusion(
    value: float | None,
) -> None:
    state, attachment, _ = _binding(Property(value, "eV", qualifier="unbound", tier="reviewed"))
    assert state.verdict == attachment.verdict == "fail"
    assert state.proposition == attachment.proposition == "ground_anion_electron_binding"
    assert "electron binding" in attachment.message


@pytest.mark.parametrize(
    ("value", "uncertainty"),
    [
        (0.0, None),
        (0.5, Uncertainty(absolute=1.0)),
        (-0.5, Uncertainty(absolute=1.0)),
        (-0.5, Uncertainty(note="precision not established")),
        (-0.5, Uncertainty(absolute=-1.0)),
    ],
)
def test_unbound_qualifier_does_not_hide_an_unresolved_or_invalid_ea_range(
    value: float,
    uncertainty: Uncertainty | None,
) -> None:
    state, attachment, _ = _binding(
        Property(value, "eV", qualifier="unbound", uncertainty=uncertainty, tier="reviewed")
    )
    assert state.verdict == attachment.verdict == "unknown"


@pytest.mark.parametrize(
    "excluded",
    [
        {"tier": "imported"},
        {"status": "rejected"},
        {"status": "conflicting"},
        {"review_scope": ("ionization_energy_eV",)},
    ],
)
def test_unqualified_nonbinding_does_not_cancel_independent_qualified_ea(excluded: dict) -> None:
    positive = Property(1.0, "eV", source="binding", tier="reviewed")
    unbound = replace(positive, value=None, qualifier="unbound", source="nonbinding", **excluded)
    first, second = _binding(positive, unbound), _binding(unbound, positive)
    assert first == second
    assert first[0].verdict == "pass"
    assert first[1].verdict == "pass"
    assert first[2]["electron_affinity_eV"] == 1.0
    assert first[0].basis == ("binding",)


def test_binding_conflict_excludes_only_ea_and_preserves_its_original_declaration() -> None:
    neutral = candidate_state({"Ar": 1}, 0)
    affinity = Property(1.0, "eV", qualifier="unbound", tier="reviewed")
    ionization = Property(10.0, "eV", tier="reviewed")
    record = StateRecord(
        "source",
        neutral,
        properties={"electron_affinity_eV": affinity, "ionization_energy_eV": ionization},
    )
    matched = StateEvidence("exact", (record,))
    selected = _preferred_state(neutral.id, {neutral.id: matched})
    assert selected is not None
    assert "electron_affinity_eV" not in selected.properties
    assert selected.properties["ionization_energy_eV"] == ionization
    assert record.properties["electron_affinity_eV"] == affinity


@pytest.mark.parametrize(
    ("affinity", "verdict"), [(None, "unknown"), (-1.0, "fail"), (1.0, "pass")]
)
@pytest.mark.parametrize("tier", ["imported", "reviewed"])
def test_short_lifetime_does_not_override_independent_ground_anion_binding(
    affinity: float | None,
    verdict: str,
    tier: str,
) -> None:
    neutral, anion = (candidate_state({"Ar": 1}, charge) for charge in (0, -1))
    candidates = CandidateSet(states={state.id: state for state in (neutral, anion)})
    transient = StateRecord(
        "short lived",
        anion,
        existence="transient",
        existence_source="lifetime evidence",
        tier=tier,
    )
    parent = StateRecord(
        "binding",
        neutral,
        properties={"electron_affinity_eV": Property(affinity, "eV", tier="reviewed")},
    )
    evidence = {
        neutral.id: StateEvidence("exact", (parent,)),
        anion.id: StateEvidence("exact", (transient,)),
    }
    result = assess_state(anion, evidence[anion.id], candidates, evidence)
    assert result.verdict == verdict
    if affinity is not None:
        assert result.proposition == "ground_anion_electron_binding"


@pytest.mark.parametrize("kind", ["ground", "electronic"])
def test_transient_does_not_mean_electron_unbound_resonance(kind: str) -> None:
    state = candidate_state({"Ar": 1}, 0, kind, resolution="resolved")
    transient = StateRecord(
        "short lived",
        state,
        existence="transient",
        existence_source="lifetime evidence",
        tier="reviewed",
    )
    result = assess_state(
        state, StateEvidence("exact", (transient,)), CandidateSet(states={state.id: state})
    )
    assert result.verdict == "unknown"
    assert "short lifetime" in result.message


@pytest.mark.parametrize(("existence", "verdict"), [("confirmed", "pass"), ("unbound", "fail")])
def test_short_lifetime_does_not_conflict_with_an_independent_bound_state_assertion(
    existence: str,
    verdict: str,
) -> None:
    state = candidate_state({"Ar": 1}, 0)
    transient = StateRecord(
        "a-short-lived",
        state,
        existence="transient",
        existence_source="lifetime evidence",
        tier="reviewed",
    )
    explicit = replace(transient, id="z-explicit", existence=existence, existence_source="binding")
    candidates = CandidateSet(states={state.id: state})
    first = assess_state(state, StateEvidence("exact", (transient, explicit)), candidates)
    second = assess_state(state, StateEvidence("exact", (explicit, transient)), candidates)
    assert first == second
    assert first.verdict == verdict
    assert first.proposition == "state_existence_support"
