"""Existence conflicts with an exact target do not invalidate independent quantities.

The declarations and analytical NASA polynomials are synthetic. These tests
verify the scope of conclusions and persistence, not the existence of F2.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.assessment import (
    _energy_property_bounds,
    _preferred_state,
    assess_state,
    assess_state_thermochemistry,
    evaluate,
)
from reactgen.case import Case, Conditions
from reactgen.chemistry import candidate_state, electron_state
from reactgen.evidence import EvidenceCatalog, StateEvidence
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.records import FormationReference, Property, StateRecord, Thermo, state_record_payload


def declarations() -> tuple[StateRecord, ...]:
    atom, molecule = (candidate_state({"F": count}, 0) for count in (1, 2))
    model = Thermo(
        (3.5, 0, 0, 0, 0, 0, 0),
        (3.5, 0, 0, 0, 0, 0, 0),
        200,
        1000,
        6000,
        source="analytical model",
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
        review_scope=("thermochemical_model",),
    )
    quantities = StateRecord(
        "independent quantities",
        molecule,
        properties={
            name: Property(
                value,
                "eV",
                source=name,
                tier="reviewed",
                review_scope=(name,),
                definition="adiabatic" if name == "ionization_energy_eV" else None,
                formation_reference=FormationReference(0, "standard_elements", 100000)
                if name == "enthalpy_formation_eV"
                else None,
            )
            for name, value in (("ionization_energy_eV", 9.0), ("enthalpy_formation_eV", 2.0))
        },
        thermo=model,
        record_id="quantities",
    )
    positive = StateRecord(
        "positive",
        molecule,
        existence="confirmed",
        existence_source="positive evidence",
        tier="reviewed",
        review_scope=("state_existence",),
        record_id="positive",
    )
    negative = replace(
        positive,
        id="negative",
        record_id="negative",
        existence="unbound",
        existence_source="negative evidence",
    )
    return (
        StateRecord(
            "atom quantities",
            atom,
            properties={
                "enthalpy_formation_eV": Property(
                    0.0,
                    "eV",
                    tier="reviewed",
                    formation_reference=FormationReference(0, "standard_elements", 100000),
                )
            },
            thermo=model,
            record_id="atom",
        ),
        quantities,
        positive,
        negative,
    )


def thermal_evaluation(records: tuple[StateRecord, ...]):
    atom, molecule = (candidate_state({"F": count}, 0) for count in (1, 2))
    reaction = ReactionCandidate(
        "split",
        (Term(molecule.id),),
        (Term(atom.id, 2),),
        "neutral",
        "dissociation",
        "test",
        "test",
        0,
    )
    candidates = CandidateSet(
        states={state.id: state for state in (atom, molecule)}, reactions={reaction.id: reaction}
    )
    return evaluate(
        candidates, EvidenceCatalog(state_records=records), Conditions(gas_temperature_K=300)
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_existence_conflict_preserves_exact_quantity_identity_and_conditional_thermal_values(
    reverse: bool,
) -> None:
    atom, quantities, positive, negative = declarations()
    baseline = thermal_evaluation((atom, quantities, positive))
    records = (atom, quantities, positive, negative)
    actual = thermal_evaluation(tuple(reversed(records)) if reverse else records)
    state_id = quantities.candidate.id
    matched = actual.state_evidence[state_id]
    existence = actual.state_assessments[state_id]["state"]
    assert matched.match == "exact"
    assert {record.candidate.key for record in matched.records} == {quantities.candidate.key}
    assert existence.verdict == "unknown"
    assert existence.proposition == "state_existence_support"
    assert "existence assertions conflict" in existence.message
    assert actual.reaction_assessments["split"]["state"].verdict == "unknown"
    assert (
        actual.state_assessments[state_id]["thermochemistry"]
        == (baseline.state_assessments[state_id]["thermochemistry"])
    )
    assert actual.thermochemistry == baseline.thermochemistry
    values = actual.thermochemistry["split"]
    assert values["delta_h_eV"] == -2.0
    assert {"delta_g_eV", "equilibrium_constant_number_density"} <= values.keys()
    assert _energy_property_bounds(matched, "ionization_energy_eV")[0] == (9.0, 9.0)


def test_conflicting_existence_survives_snapshot_ingest_adopt_without_losing_qualified_quantities(
    tmp_path: Path,
) -> None:
    records = declarations()
    source = tmp_path / "snapshot.yaml"
    source.write_text(
        yamlio.dump({"snapshot_version": 1, "records": [state_record_payload(r) for r in records]}),
        encoding="utf-8",
    )
    case = Case("synthetic boundary", ("F2",), conditions=Conditions(gas_temperature_K=300))
    direct = analyze(case, EvidenceCatalog.load_paths((source,)))
    bundle, overlay = tmp_path / "bundle", tmp_path / "overlay.yaml"
    export.write(bundle, direct)
    assert ingest.ingest(source, bundle, overlay).accepted == len(records)
    root = tmp_path / "registry"
    for count in (1, 2):
        directory = root / "species"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"F{count}.yaml").write_text(
            yamlio.dump(
                {"id": "F" if count == 1 else "F2", "composition": {"F": count}, "phase": "gas"}
            ),
            encoding="utf-8",
        )
    assert adopt.adopt(overlay, root).values == len(records)
    for catalog in (
        EvidenceCatalog.load_paths((source,)),
        EvidenceCatalog.load_paths((overlay,)),
        EvidenceCatalog.load(root),
    ):
        analysis = analyze(case, catalog)
        evidence = analysis.evaluation.state_evidence["F2@ground"]
        judgments = analysis.evaluation.state_assessments["F2@ground"]
        assert evidence.match == "exact"
        assert judgments["state"].verdict == "unknown"
        assert "existence assertions conflict" in judgments["state"].message
        assert judgments["thermochemistry"].verdict == "pass"
        assert _energy_property_bounds(evidence, "ionization_energy_eV")[0] == (9.0, 9.0)
        assert analysis.evaluation.thermochemistry == direct.evaluation.thermochemistry
        document = export.document(analysis)
        saved = next(state for state in document["states"] if state["id"] == "F2@ground")
        assert saved["evidence"]["match"] == "exact"
        assert saved["assessments"]["state"]["verdict"] == "unknown"
        assert saved["assessments"]["thermochemistry"]["verdict"] == "pass"


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_invalid_parent_still_excludes_its_entire_quantity_declaration(status: str) -> None:
    _, quantities, positive, negative = declarations()
    invalid = replace(quantities, status=status)
    state = quantities.candidate
    evidence = EvidenceCatalog(state_records=(positive, negative, invalid)).state(state)
    assert evidence.match == "exact"
    assert assess_state_thermochemistry(state, evidence).verdict == "unknown"
    assert _energy_property_bounds(evidence, "ionization_energy_eV")[0] is None
    selected = _preferred_state(state.id, {state.id: evidence})
    assert selected is not None
    assert not selected.properties
    assert selected.thermo is None
    # A separate valid record may provide the quantity; it cannot revive invalid.
    combined = EvidenceCatalog(state_records=(positive, negative, invalid, quantities)).state(state)
    assert assess_state_thermochemistry(state, combined).verdict == "pass"
    assert _energy_property_bounds(combined, "ionization_energy_eV")[0] == (9.0, 9.0)


def test_true_identity_ambiguity_still_blocks_quantity_use() -> None:
    _, quantities, _, _ = declarations()
    state = quantities.candidate
    unresolved = StateEvidence("ambiguous", (quantities,))
    judgment = assess_state(state, unresolved, CandidateSet(states={state.id: state}))
    assert judgment.verdict == "unknown"
    assert assess_state_thermochemistry(state, unresolved).verdict == "unknown"
    assert _energy_property_bounds(unresolved, "ionization_energy_eV")[0] is None
    assert _preferred_state(state.id, {state.id: unresolved}) is None


@pytest.mark.parametrize("changes", [{"phase": "solid"}, {"structure": "another structure"}])
def test_a_different_physical_target_still_cannot_supply_qualified_quantities(
    changes: dict,
) -> None:
    _, quantities, _, _ = declarations()
    target = replace(quantities.candidate, **changes)
    evidence = EvidenceCatalog(state_records=(quantities,)).state(target)
    assert evidence.match != "exact"
    assert assess_state_thermochemistry(target, evidence).verdict == "unknown"
    assert _energy_property_bounds(evidence, "ionization_energy_eV")[0] is None


def test_an_explicit_existence_conflict_cannot_be_overridden_by_affinity_inference() -> None:
    neutral, anion = (candidate_state({"F": 1}, charge) for charge in (0, -1))
    affinity = StateRecord(
        "affinity", neutral, properties={"electron_affinity_eV": Property(1, "eV", tier="reviewed")}
    )
    conflict = StateRecord(
        "explicit conflict", anion, status="conflicting", review_scope=("state_existence",)
    )
    catalog = EvidenceCatalog(state_records=(affinity, conflict))
    candidates = CandidateSet(
        states={state.id: state for state in (electron_state(), neutral, anion)}
    )
    evidence = {state.id: catalog.state(state) for state in candidates.states.values()}
    judgment = assess_state(anion, evidence[anion.id], candidates, evidence)
    assert evidence[anion.id].match == "exact"
    assert judgment.verdict == "unknown"
    assert judgment.proposition == "state_existence_support"
    assert "existence assertions conflict" in judgment.message
