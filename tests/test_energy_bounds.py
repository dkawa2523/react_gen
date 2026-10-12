"""Declared IE ranges constrain a threshold point without inventing its precision."""

from dataclasses import replace

import pytest

from reactgen.assessment import (
    _preferred_state,
    assess_consistency,
    assess_state,
    assess_thermochemistry,
)
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.model import (
    Assessment,
    CandidateSet,
    CandidateState,
    ReactionCandidate,
    StateCandidate,
    Term,
)
from reactgen.records import Property, ReactionRecord, StateRecord, Uncertainty
from reactgen.units import AVOGADRO, EV_PER_K, JOULE_PER_EV, quantity_value


def _ionization(
    threshold: float,
    *properties: Property,
    extra_threshold: float | None = None,
) -> tuple[Assessment, dict[str, float]]:
    parent, ion = (candidate_state({"Ar": 1}, charge) for charge in (1, 2))
    reaction = ReactionCandidate(
        "step-ionization",
        (Term("e"), Term(parent.id)),
        (Term("e", 2), Term(ion.id)),
        "electron",
        "ionization",
        "test",
        "test",
        0,
    )
    states = {
        parent.id: StateEvidence(
            "exact",
            tuple(
                StateRecord(
                    str(index),
                    parent,
                    properties={"ionization_energy_eV": prop},
                    tier="reviewed",
                    source={"citation": f"IE declaration {index}"},
                )
                for index, prop in enumerate(properties)
            ),
        )
    }
    record = ReactionRecord(
        "threshold",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (parent, ion),
        energy_properties={"threshold_eV": Property(threshold, "eV", tier="reviewed")},
        tier="reviewed",
        source={"citation": "threshold declaration"},
    )
    records = (
        (record,)
        if extra_threshold is None
        else (
            record,
            replace(
                record,
                id="another-threshold",
                energy_properties={
                    "threshold_eV": Property(extra_threshold, "eV", tier="reviewed")
                },
            ),
        )
    )
    return assess_thermochemistry(
        reaction,
        CandidateSet(states={state.id: state for state in (parent, ion)}),
        states,
        ReactionEvidence(records),
        Conditions(),
    )


@pytest.mark.parametrize(
    ("unit", "scale"),
    [
        ("eV", 1.0),
        ("J", JOULE_PER_EV),
        ("J/mol", JOULE_PER_EV * AVOGADRO),
        ("kJ/mol", JOULE_PER_EV * AVOGADRO / 1000),
        ("K", 1 / EV_PER_K),
    ],
)
@pytest.mark.parametrize(
    ("threshold", "verdict"), [(9.5, "fail"), (10.0, "unknown"), (10.5, "pass")]
)
def test_absolute_ie_range_is_converted_with_its_property_unit(
    unit: str, scale: float, threshold: float, verdict: str
) -> None:
    prop = Property(
        10.0 * scale,
        unit,
        source="unit-specific IE source",
        uncertainty=Uncertainty(absolute=0.2 * scale),
        tier="reviewed",
    )
    result, values = _ionization(threshold, prop)
    assert result.verdict == verdict
    assert values["ionization_energy_eV"] == pytest.approx(10.0, rel=1e-12, abs=0)
    assert "declared threshold point" in result.message
    assert "IE declaration range" in result.message
    assert "threshold measurement uncertainty" in result.message
    assert "unit-specific IE source" in result.basis
    assert "threshold declaration" in result.basis


@pytest.mark.parametrize(("threshold", "verdict"), [(9.8, "unknown"), (10.2, "pass")])
def test_ie_interval_boundaries_do_not_use_its_central_value(
    threshold: float, verdict: str
) -> None:
    prop = Property(10.0, "eV", uncertainty=Uncertainty(absolute=0.2), tier="reviewed")
    assert _ionization(threshold, prop)[0].verdict == verdict


def test_nist_argon_ion_uncertainty_does_not_falsely_exclude_a_threshold_point() -> None:
    # NIST ASD Ar II: 27.62967 +/- 0.00012 eV, not an exact 27.62967 eV bound.
    prop = Property(27.62967, "eV", uncertainty=Uncertainty(absolute=0.00012), tier="reviewed")
    result, _ = _ionization(27.62960, prop)
    assert result.verdict == "unknown"
    assert "27.62955" in result.message
    assert "27.62979" in result.message


@pytest.mark.parametrize(
    ("uncertainty", "threshold", "verdict"),
    [
        (Uncertainty(factor=2), 4.0, "fail"),
        (Uncertainty(factor=2), 6.0, "unknown"),
        (Uncertainty(factor=2), 20.0, "pass"),
        (Uncertainty(relative=0.02), 9.5, "fail"),
        (Uncertainty(relative=0.02), 10.0, "unknown"),
        (Uncertainty(relative=0.02), 10.5, "pass"),
        (Uncertainty(absolute=0), 10.0, "pass"),
    ],
)
def test_supported_uncertainty_declarations_determine_the_reported_ie_range(
    uncertainty: Uncertainty, threshold: float, verdict: str
) -> None:
    prop = Property(10.0, "eV", uncertainty=uncertainty, tier="reviewed")
    assert _ionization(threshold, prop)[0].verdict == verdict


@pytest.mark.parametrize(
    "uncertainty",
    [
        Uncertainty(absolute=-0.1),
        Uncertainty(relative=float("nan")),
        Uncertainty(factor=0.9),
        Uncertainty(absolute=float("inf")),
        Uncertainty(note="precision is unspecified"),
    ],
)
def test_invalid_or_nonquantitative_ie_uncertainty_cannot_support_a_precision_claim(
    uncertainty: Uncertainty,
) -> None:
    prop = Property(10.0, "eV", uncertainty=uncertainty, tier="reviewed")
    result, values = _ionization(20.0, prop)
    assert result.verdict == "unknown"
    assert values["ionization_energy_eV"] == 10.0


def test_same_ie_value_does_not_select_a_narrower_uncertainty_by_source_order() -> None:
    narrow = Property(10.0, "eV", uncertainty=Uncertainty(absolute=0.1), tier="reviewed")
    wide = replace(narrow, uncertainty=Uncertainty(absolute=0.2))
    first, second = _ionization(9.85, narrow, wide), _ionization(9.85, wide, narrow)
    assert first == second
    assert first[0].verdict == "unknown"
    assert "[9.8, 10.2]" in first[0].message


def test_conflicting_reviewed_threshold_points_remain_unknown() -> None:
    prop = Property(10.0, "eV", uncertainty=Uncertainty(absolute=0.2), tier="reviewed")
    result, values = _ionization(10.5, prop, extra_threshold=11.0)
    assert result.verdict == "unknown"
    assert "threshold_eV" not in values


def test_conflicting_reviewed_ie_values_remain_unknown() -> None:
    first = Property(10.0, "eV", uncertainty=Uncertainty(absolute=0.2), tier="reviewed")
    result, values = _ionization(20.0, first, replace(first, value=11.0))
    assert result.verdict == "unknown"
    assert "ionization_energy_eV" not in values


def test_unreviewed_ie_does_not_gain_support_from_a_reviewed_threshold() -> None:
    result, values = _ionization(20.0, Property(10.0, "eV"))
    assert result.verdict == "unknown"
    assert "ionization_energy_eV" not in values


def test_point_declarations_do_not_invent_a_one_microelectronvolt_tolerance() -> None:
    prop = Property(10.0, "eV", tier="reviewed")
    assert _ionization(10.0 - 5e-7, prop)[0].verdict == "fail"
    assert _ionization(10.0, prop)[0].verdict == "pass"


def test_unit_conversion_roundoff_does_not_create_a_hard_exclusion() -> None:
    prop = Property(10.0, "eV", tier="reviewed")
    assert _ionization(10.0 - 1e-14, prop)[0].verdict == "unknown"


@pytest.mark.parametrize(("existence", "verdict"), [("unknown", "unknown"), ("confirmed", "pass")])
def test_energy_aggregate_preserves_raw_declarations_and_does_not_change_state_support(
    existence: str, verdict: str
) -> None:
    state = candidate_state({"Ar": 1}, 0, "electronic", label="level", resolution="resolved")
    imported = StateRecord(
        "legacy",
        state,
        energy_eV=20.0,
        existence=existence,
        existence_source="independent existence support" if existence == "confirmed" else None,
        tier="reviewed",
        properties={"excitation_energy_eV": Property(20.0, "eV", tier="imported")},
    )
    reviewed = StateRecord(
        "reviewed-energy",
        state,
        properties={"excitation_energy_eV": Property(21.0, "eV", tier="reviewed")},
    )
    candidates = CandidateSet(states={state.id: state})
    before = EvidenceCatalog(state_records=(imported,)).state(state)
    for records in ((imported, reviewed), (reviewed, imported)):
        evidence = EvidenceCatalog(state_records=records).state(state)
        assert evidence.match == "exact"
        selected = _preferred_state(state.id, {state.id: evidence})
        assert selected is not None
        assert selected.energy_eV is None
        assert (
            selected.properties["excitation_energy_eV"]
            == reviewed.properties["excitation_energy_eV"]
        )
        assert imported.energy_eV == 20.0
        assert imported.properties["excitation_energy_eV"].value == 20.0
        assert len(evidence.records) == len(records)
        assert all(original in evidence.records for original in records)
        assert all(original is not record for original in records for record in evidence.records)
        judgment = assess_state(state, evidence, candidates)
        baseline = assess_state(state, before, candidates)
        assert (judgment.verdict, judgment.message) == (baseline.verdict, baseline.message)
        assert judgment.verdict == verdict


@pytest.mark.parametrize(
    ("tier", "energy_unit", "energy", "legacy_energy", "verdict"),
    [
        ("imported", "eV", 12.0, 12.0, "unknown"),
        ("reviewed", "J", 12.0 * JOULE_PER_EV, None, "pass"),
        ("reviewed", "A3", 12.0, 12.0, "unknown"),
    ],
)
def test_penning_uses_energy_property_qualification_instead_of_state_qualification(
    tier: str, energy_unit: str, energy: float, legacy_energy: float | None, verdict: str
) -> None:
    excited = candidate_state({"Ar": 1}, 0, "electronic", label="level", resolution="resolved")
    ground = candidate_state({"Ar": 1}, 0)
    target, ion = (candidate_state({"O": 2}, charge) for charge in (0, 1))
    reaction = ReactionCandidate(
        "penning",
        (Term(excited.id), Term(target.id)),
        (Term(ground.id), Term(ion.id), Term("e")),
        "neutral",
        "penning_ionization",
        "test",
        "test",
        0,
    )
    states = {
        excited.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    excited.id,
                    excited,
                    energy_eV=legacy_energy,
                    tier="reviewed",
                    existence="confirmed",
                    existence_source="existence review only",
                    properties={"excitation_energy_eV": Property(energy, energy_unit, tier=tier)},
                ),
            ),
        ),
        target.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    target.id,
                    target,
                    properties={
                        "ionization_energy_eV": Property(
                            10.0, "eV", tier="reviewed", definition="adiabatic"
                        )
                    },
                ),
            ),
        ),
    }
    result, values = assess_thermochemistry(
        reaction,
        CandidateSet(states={state.id: state for state in (excited, ground, target, ion)}),
        states,
        ReactionEvidence(),
        Conditions(),
    )
    assert result.verdict == verdict
    if verdict == "pass":
        assert values["penning_available_energy_eV"] == pytest.approx(2.0, rel=1e-12, abs=0)
    else:
        assert "penning_available_energy_eV" not in values


def _affinity_inference(*properties: Property) -> tuple[Assessment, Assessment]:
    neutral, anion = (candidate_state({"O": 2}, charge) for charge in (0, -1))
    electron = StateCandidate("e", {}, -1, CandidateState("ground", "resolved"))
    candidates = CandidateSet(states={state.id: state for state in (neutral, anion, electron)})
    evidence = {
        neutral.id: StateEvidence(
            "exact",
            tuple(
                StateRecord(
                    str(index),
                    neutral,
                    properties={"electron_affinity_eV": replace(prop, definition="adiabatic")},
                )
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
    return (
        assess_state(anion, StateEvidence("none", ()), candidates, evidence),
        assess_thermochemistry(reaction, candidates, evidence, ReactionEvidence(), Conditions())[0],
    )


@pytest.mark.parametrize("value", [-0.5, 0.5])
def test_note_only_affinity_uncertainty_is_not_an_exact_binding_energy(value: float) -> None:
    prop = Property(value, "eV", tier="reviewed", uncertainty=Uncertainty(note="unspecified"))
    state, attachment = _affinity_inference(prop)
    assert state.verdict == attachment.verdict == "unknown"


@pytest.mark.parametrize("value", [-0.5, 0.5])
def test_affinity_range_retains_all_declared_errors_and_sources(value: float) -> None:
    narrow = Property(
        value, "eV", source="narrow", tier="reviewed", uncertainty=Uncertainty(absolute=0.1)
    )
    wide = replace(narrow, source="wide", uncertainty=Uncertainty(absolute=1.0))
    first, second = _affinity_inference(narrow, wide), _affinity_inference(wide, narrow)
    assert first == second
    assert first[0].verdict == first[1].verdict == "unknown"
    assert set(first[0].basis) == {"narrow", "wide"}


def _penning_ranges(
    excitation: Property,
    ionization: Property,
    *,
    collision: float | None = None,
    donor_product_kind: str = "ground",
    ion_product_kind: str = "ground",
    donor_product_structure: str | None = None,
    ion_product_charge: int = 1,
    additional_excitation: Property | None = None,
) -> tuple[Assessment, dict[str, float]]:
    donor = candidate_state({"Ar": 1}, 0, "electronic", label="level", resolution="resolved")
    target = candidate_state({"O": 2}, 0)
    donor_product = candidate_state(
        {"Ar": 1}, 0, donor_product_kind, resolution="resolved", structure=donor_product_structure
    )
    ion = candidate_state({"O": 2}, ion_product_charge, ion_product_kind, resolution="resolved")
    electron = StateCandidate("e", {}, -1, CandidateState("ground", "resolved"))
    candidates = CandidateSet(
        states={state.id: state for state in (donor, target, donor_product, ion, electron)}
    )
    reaction = ReactionCandidate(
        "penning",
        (Term(donor.id), Term(target.id)),
        (Term(donor_product.id), Term(ion.id), Term("e")),
        "neutral",
        "penning_ionization",
        "test",
        "test",
        0,
    )
    evidence = {
        donor.id: StateEvidence(
            "exact",
            tuple(
                StateRecord(str(index), donor, properties={"excitation_energy_eV": prop})
                for index, prop in enumerate(
                    (excitation, additional_excitation) if additional_excitation else (excitation,)
                )
            ),
        ),
        target.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    "target",
                    target,
                    properties={
                        "ionization_energy_eV": replace(ionization, definition="adiabatic")
                    },
                ),
            ),
        ),
    }
    if ion_product_charge == 1:
        assert assess_consistency(reaction, candidates).verdict == "pass"
    return assess_thermochemistry(
        reaction,
        candidates,
        evidence,
        ReactionEvidence(),
        Conditions(collision_energy_eV=collision),
    )


@pytest.mark.parametrize("quantity", ["excitation_energy_eV", "ionization_energy_eV"])
@pytest.mark.parametrize("qualifier", ["upper limit", "lower limit"])
def test_penning_does_not_consume_free_energy_qualifiers_as_declared_points(
    quantity: str,
    qualifier: str,
) -> None:
    excitation = Property(12, "eV", tier="reviewed")
    ionization = Property(10, "eV", tier="reviewed", definition="adiabatic")
    if quantity == "excitation_energy_eV":
        excitation = replace(excitation, qualifier=qualifier)
    else:
        ionization = replace(ionization, qualifier=qualifier)
    result, values = _penning_ranges(excitation, ionization)
    assert result.verdict == "unknown"
    assert "penning_available_energy_eV" not in values
    assert {(item.responsibility, item.quantity) for item in result.requirements} == {
        ("source_review", f"{quantity}.qualifier"),
    }


@pytest.mark.parametrize("excitation", [9.9, 10.1])
@pytest.mark.parametrize("collision", [None, 0.0])
def test_penning_error_overlap_cannot_decide_an_energy_requirement(
    excitation: float, collision: float | None
) -> None:
    energy = Property(
        excitation,
        "eV",
        source="level source",
        tier="reviewed",
        uncertainty=Uncertainty(absolute=0.2),
    )
    ie = Property(
        10.0, "eV", source="IE source", tier="reviewed", uncertainty=Uncertainty(absolute=0.2)
    )
    verdict, values = _penning_ranges(energy, ie, collision=collision)
    assert verdict.verdict == "unknown"
    assert "declared available-energy range" in verdict.message
    assert set(verdict.basis) == {"level source", "IE source"}
    assert values["penning_available_energy_eV"] == pytest.approx(excitation - 10, abs=1e-12)


@pytest.mark.parametrize(
    ("excitation", "collision", "verdict"),
    [(9.0, None, "unknown"), (9.0, 0.0, "fail"), (9.0, 2.0, "pass"), (11.0, None, "pass")],
)
def test_penning_decides_only_when_the_entire_declared_budget_agrees(
    excitation: float, collision: float | None, verdict: str
) -> None:
    energy = Property(excitation, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=0.2))
    ie = Property(10.0, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=0.2))
    result, _ = _penning_ranges(energy, ie, collision=collision)
    assert result.verdict == verdict
    assert "occurrence are undetermined" in result.message


@pytest.mark.parametrize(
    "uncertainty",
    [Uncertainty(note="unspecified"), Uncertainty(absolute=-1), Uncertainty(factor=0)],
)
def test_penning_invalid_or_unspecified_errors_do_not_support_a_point_relation(
    uncertainty: Uncertainty,
) -> None:
    energy = Property(12.0, "eV", tier="reviewed", uncertainty=uncertainty)
    ie = Property(10.0, "eV", tier="reviewed")
    assert _penning_ranges(energy, ie)[0].verdict == "unknown"


def test_penning_equal_centers_keep_the_wider_error_and_conflicting_centers_are_unknown() -> None:
    energy = Property(10.1, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=0.01))
    ie = Property(10.0, "eV", tier="reviewed")
    wide = replace(energy, uncertainty=Uncertainty(absolute=0.2))
    for first, second in ((energy, wide), (wide, energy)):
        assert _penning_ranges(first, ie, additional_excitation=second)[0].verdict == "unknown"
    result, values = _penning_ranges(energy, ie, additional_excitation=replace(energy, value=12))
    assert result.verdict == "unknown"
    assert "penning_available_energy_eV" not in values


@pytest.mark.parametrize(
    "changes",
    [
        {"donor_product_kind": "electronic"},
        {"ion_product_kind": "electronic"},
        {"donor_product_structure": "another structure"},
        {"ion_product_charge": 2},
    ],
)
def test_penning_ground_energy_model_cannot_decide_different_actual_products(changes: dict) -> None:
    energy, ie = (Property(value, "eV", tier="reviewed") for value in (12.0, 10.0))
    result, values = _penning_ranges(energy, ie, **changes)
    assert result.verdict == "unknown"
    assert "corresponding ground-state products" in result.message
    assert "penning_available_energy_eV" not in values


def test_energy_axis_conversion_cannot_return_a_nonfinite_temperature() -> None:
    assert quantity_value(1e308, "electron_temperature", "eV", "K") is None


@pytest.mark.parametrize(
    ("unit", "scale"),
    [("eV", 1.0), ("J", JOULE_PER_EV), ("kJ/mol", JOULE_PER_EV * AVOGADRO / 1000)],
)
def test_penning_declared_budget_is_invariant_under_energy_units(unit: str, scale: float) -> None:
    excitation = Property(
        10.1 * scale, unit, tier="reviewed", uncertainty=Uncertainty(absolute=0.2 * scale)
    )
    ie = Property(10.0, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=0.2))
    assert _penning_ranges(excitation, ie, collision=0.0)[0].verdict == "unknown"


def test_penning_budget_overflow_does_not_become_an_energy_pass() -> None:
    excitation = Property(1e308, "eV", tier="reviewed")
    ie = Property(10.0, "eV", tier="reviewed")
    result, _ = _penning_ranges(excitation, ie, collision=1e308)
    assert result.verdict == "unknown"
    assert "not finite" in result.message


@pytest.mark.parametrize("phase", ["gas", "solid"])
def test_affinity_parent_selection_respects_the_actual_phase_and_structure(phase: str) -> None:
    wrong_parent = candidate_state({"O": 2}, 0, phase="gas", structure="other isomer")
    parent = candidate_state({"O": 2}, 0, phase=phase, structure="requested isomer")
    anion = candidate_state({"O": 2}, -1, phase=phase, structure="requested isomer")
    candidates = CandidateSet(states={state.id: state for state in (wrong_parent, parent, anion)})
    evidence = {
        wrong_parent.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    "wrong",
                    wrong_parent,
                    properties={"electron_affinity_eV": Property(1.0, "eV", tier="reviewed")},
                ),
            ),
        )
    }
    verdict = assess_state(anion, StateEvidence("none", ()), candidates, evidence)
    assert verdict.verdict == "unknown"


def test_parent_affinity_does_not_exclude_attachment_into_an_excited_anion() -> None:
    parent = candidate_state({"O": 2}, 0)
    anion = candidate_state({"O": 2}, -1, "electronic", label="resonance", resolution="resolved")
    electron = StateCandidate("e", {}, -1, CandidateState("ground", "resolved"))
    candidates = CandidateSet(states={state.id: state for state in (parent, anion, electron)})
    evidence = {
        parent.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    "parent",
                    parent,
                    properties={
                        "electron_affinity_eV": Property(
                            -1.0, "eV", qualifier="unbound", tier="reviewed"
                        )
                    },
                ),
            ),
        )
    }
    reaction = ReactionCandidate(
        "attachment",
        (Term("e"), Term(parent.id)),
        (Term(anion.id),),
        "electron",
        "attachment",
        "test",
        "test",
        0,
    )
    assert assess_consistency(reaction, candidates).verdict == "pass"
    verdict, _ = assess_thermochemistry(
        reaction, candidates, evidence, ReactionEvidence(), Conditions()
    )
    assert verdict.verdict == "unknown"


@pytest.mark.parametrize("value", [0.1, 27.62967])
def test_energy_source_centers_are_invariant_under_unit_conversion_roundoff(value: float) -> None:
    ev = Property(value, "eV", source="eV source", tier="reviewed")
    joule = replace(ev, value=value * JOULE_PER_EV, unit="J", source="joule source")
    first, second = _affinity_inference(ev, joule), _affinity_inference(joule, ev)
    assert first == second
    assert first[0].verdict == "pass"
    assert set(first[0].basis) == {"eV source", "joule source"}
    ionization, values = _ionization(value + 1, ev, joule)
    assert ionization.verdict == "pass"
    assert values["ionization_energy_eV"] == pytest.approx(value, rel=1e-12, abs=0)


def test_roundoff_matching_does_not_merge_different_same_unit_declarations() -> None:
    original = Property(0.1, "eV", tier="reviewed")
    different = replace(original, value=0.1 + 1e-14)
    assert _affinity_inference(original, different)[0].verdict == "unknown"
    result, values = _ionization(1.0, original, different)
    assert result.verdict == "unknown"
    assert "ionization_energy_eV" not in values
