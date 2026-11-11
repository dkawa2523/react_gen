"""Quantity source requests preserve identity, qualification and raw alternatives."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import export, yamlio
from reactgen.assessment import evaluate
from reactgen.case import Case, Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.records import FormationReference, Property, SourceRef, StateRecord, Thermo
from reactgen.selection import STATE_QUANTITIES, DataSelection


def policy(quantity="enthalpy_formation_eV", **options):
    return DataSelection.from_document({"quantities": {quantity: options}})


def inputs():
    atom, molecule = (candidate_state({"F": count}, 0) for count in (1, 2))
    fit = Thermo(
        (3.5, 0, 0, 0, 0, 0, 0),
        (3.5, 0, 0, 0, 0, 0, 0),
        200,
        1000,
        6000,
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
        provenance=SourceRef(provider="external"),
        method="evaluated",
    )
    reference = FormationReference(298.15, "standard_elements", 100000)
    records = tuple(
        StateRecord(
            state.id,
            state,
            record_id=f"{state.id}:external",
            properties={
                "enthalpy_formation_eV": Property(
                    value,
                    "eV",
                    tier="reviewed",
                    formation_reference=reference,
                    provenance=SourceRef(provider="external"),
                    method="evaluated",
                )
            },
            thermo=fit,
        )
        for state, value in ((atom, 1.0), (molecule, 3.0))
    )
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
    return reaction, records


def run(records, selection=None, temperature=300):
    reaction, _ = inputs()
    return evaluate(
        CandidateSet(
            states={record.candidate.id: record.candidate for record in records},
            reactions={reaction.id: reaction},
        ),
        EvidenceCatalog(state_records=tuple(records)),
        Conditions(gas_temperature_K=temperature),
        selection,
    )


def alternative(record, *, value=5.0, provider="local_lab", **changes):
    original = record.properties["enthalpy_formation_eV"]
    return replace(
        record,
        record_id=f"{record.candidate.id}:{provider}",
        properties={
            "enthalpy_formation_eV": replace(
                original, value=value, provenance=SourceRef(provider=provider), **changes
            )
        },
        thermo=None,
    )


@pytest.mark.parametrize("quantity", sorted(STATE_QUANTITIES))
def test_public_state_quantity_selection_round_trips(quantity):
    request = policy(quantity, providers=["local_lab", "external"])
    case = Case("sample", ("F2",), data_selection=request)
    assert Case.from_document(case.document()) == case
    with pytest.raises(ValueError, match="unsupported"):
        policy("unsupported_test_quantity", providers=["local_lab"])


@pytest.mark.parametrize("reverse", [False, True])
def test_hf_selection_resolves_one_quantity_and_keeps_all_raw_records(reverse):
    _, (atom, molecule) = inputs()
    local = alternative(molecule)
    records = [atom, molecule, local]
    if reverse:
        records.reverse()
    unselected = run(records)
    assert unselected.thermochemical_calculations["split"]["delta_h_eV"].status == "unavailable"
    selected = run(records, policy(providers=["local_lab", "external"]))
    calculations = selected.thermochemical_calculations["split"]
    assert calculations["delta_h_eV"].value == -3.0
    assert calculations["delta_g_eV"].status == "computed"
    evidence = selected.state_evidence[molecule.candidate.id]
    assert {record.record_id for record in evidence.records} == {
        molecule.record_id,
        local.record_id,
    }
    assert all(record.existence == "unknown" for record in evidence.records)


def test_only_requests_allow_switching_between_external_and_local_records():
    _, (atom, molecule) = inputs()
    local = alternative(molecule)
    local_atom = alternative(atom, value=1.0)
    records = (atom, molecule, local, local_atom)
    for provider, expected in (("external", -1.0), ("local_lab", -3.0)):
        selected = run(records, policy(mode="only", providers=[provider]))
        assert selected.thermochemical_calculations["split"]["delta_h_eV"].value == expected


def test_prefer_does_not_choose_a_different_hf_reference_condition():
    _, (atom, molecule) = inputs()
    local = alternative(
        molecule, formation_reference=FormationReference(500, "standard_elements", 100000)
    )
    selected = run((atom, molecule, local), policy(providers=["local_lab", "external"]))
    calculation = selected.thermochemical_calculations["split"]["delta_h_eV"]
    assert calculation.status == "unavailable"
    assert any(item.responsibility == "source_review" for item in calculation.requirements)


def test_preferred_unreviewed_or_invalid_value_cannot_hide_a_qualified_value():
    _, (atom, molecule) = inputs()
    for changes in ({"tier": "imported"}, {"unit": "unsupported"}, {"status": "rejected"}):
        local = alternative(molecule, **changes)
        selected = run((atom, molecule, local), policy(providers=["local_lab", "external"]))
        assert selected.thermochemical_calculations["split"]["delta_h_eV"].value == -1.0


def test_missing_requested_provider_is_a_selection_action_with_existing_values():
    _, records = inputs()
    selected = run(records, policy(mode="only", providers=["not_loaded"]))
    calculation = selected.thermochemical_calculations["split"]["delta_h_eV"]
    assert calculation.status == "unavailable"
    assert {item.responsibility for item in calculation.requirements} == {"source_selection"}
    assert selected.thermochemical_calculations["split"]["delta_g_eV"].status == "computed"


@pytest.mark.parametrize(
    ("change", "missing_quantity"),
    [
        ({"unit": None}, "enthalpy_formation_eV.unit"),
        ({"formation_reference": None}, "enthalpy_formation_eV.formation_reference"),
    ],
)
def test_target_only_source_keeps_its_actual_missing_metadata(change, missing_quantity):
    _, (atom, molecule) = inputs()
    local = alternative(molecule, **change)
    request = DataSelection.from_document(
        {
            "targets": {
                molecule.candidate.id: {
                    "enthalpy_formation_eV": {"mode": "only", "providers": ["local_lab"]}
                }
            }
        }
    )
    selected = run((atom, molecule, local), request)
    calculation = selected.thermochemical_calculations["split"]["delta_h_eV"]
    assert calculation.status == "unavailable"
    assert {item.responsibility for item in calculation.requirements} == {"source_information"}
    assert missing_quantity in {item.quantity for item in calculation.requirements}


def test_fixed_state_record_is_explicit_and_does_not_qualify_unreviewed_values():
    _, (atom, molecule) = inputs()
    local = alternative(molecule, tier="imported")
    selected = run((atom, molecule, local), policy(record=local.record_id))
    calculation = selected.thermochemical_calculations["split"]["delta_h_eV"]
    assert calculation.value is None
    assert all(
        record.properties["enthalpy_formation_eV"].tier == "imported"
        for record in selected.state_evidence[molecule.candidate.id].records
        if record.record_id == local.record_id
    )
    assert selected.thermochemical_calculations["split"]["delta_g_eV"].status == "computed"


def test_fixed_state_record_for_another_quantity_is_an_input_error():
    _, (atom, molecule) = inputs()
    with pytest.raises(ValueError, match="another quantity"):
        run((atom, molecule), policy("ionization_energy_eV", record=molecule.record_id))


def test_thermal_model_selection_uses_query_domain_and_preserves_hf():
    _, (atom, molecule) = inputs()
    local = replace(
        molecule,
        record_id="molecule:local",
        properties={},
        thermo=replace(
            molecule.thermo,
            low=(7, 0, 0, 0, 0, 0, 0),
            high=(7, 0, 0, 0, 0, 0, 0),
            provenance=SourceRef(provider="local_lab"),
        ),
    )
    selected = run((atom, molecule, local), policy("thermochemical_model", providers=["local_lab"]))
    calculations = selected.thermochemical_calculations["split"]
    assert calculations["delta_h_eV"].value == -1.0
    assert calculations["delta_g_eV"].value == pytest.approx(0, abs=1e-12)
    outside = replace(local, thermo=replace(local.thermo, t_min=500))
    fallback = run(
        (atom, molecule, outside), policy("thermochemical_model", providers=["local_lab"])
    )
    assert fallback.thermochemical_calculations["split"]["delta_g_eV"].status == "computed"
    assert fallback.thermochemical_calculations["split"]["delta_g_eV"].value != pytest.approx(0)


def test_source_preference_does_not_choose_a_standard_pressure():
    _, (atom, molecule) = inputs()
    local = replace(
        molecule,
        record_id="molecule:local",
        thermo=replace(
            molecule.thermo,
            standard_pressure_Pa=101325,
            provenance=SourceRef(provider="local_lab"),
        ),
    )
    selected = run((atom, molecule, local), policy("thermochemical_model", providers=["local_lab"]))
    assert selected.thermochemical_calculations["split"]["delta_g_eV"].status == "unavailable"
    assert selected.thermochemical_calculations["split"]["delta_h_eV"].status == "computed"


def test_multiple_files_merge_and_saved_results_keep_request_and_alternatives(tmp_path: Path):
    from reactgen.records import state_record_payload

    state = candidate_state({"Ar": 1}, 0)
    records = [
        StateRecord(
            state.id,
            state,
            record_id=provider,
            properties={
                "enthalpy_formation_eV": Property(
                    value,
                    "eV",
                    tier="reviewed",
                    provenance=SourceRef(provider=provider),
                    formation_reference=FormationReference(298.15, "standard_elements", 100000),
                )
            },
        )
        for provider, value in (("external", 0.0), ("local_lab", 1.0))
    ]
    files = []
    for record in records:
        path = tmp_path / f"{record.record_id}.yaml"
        path.write_text(
            yamlio.dump({"state_records": {state.id: [state_record_payload(record)]}}),
            encoding="utf-8",
        )
        files.append(path)
    catalog = EvidenceCatalog.load_paths(tuple(files))
    request = policy(providers=["local_lab", "external"])
    result = analyze(Case("argon", ("Ar",), data_selection=request), catalog)
    export.write(tmp_path / "result", result)
    saved = export.read(tmp_path / "result", verify_views=True)
    assert saved["input"]["data_selection"] == request.document()
    ground = next(item for item in saved["states"] if item["id"] == state.id)
    assert len(ground["evidence"]["records"]) == 2
    assert ground["assessments"]["thermochemistry"]["verdict"] == "pass"
    assert ground["assessments"]["thermochemistry"]["basis"] == ["local_lab"]


def test_direct_evaluation_requires_a_validated_source_request():
    _, records = inputs()
    with pytest.raises(ValueError, match="validated DataSelection"):
        run(records, {"quantities": {}})


def test_target_record_override_preserves_other_species_global_fallback():
    _, (atom, molecule) = inputs()
    local = alternative(molecule)
    request = DataSelection.from_document(
        {
            "quantities": {"enthalpy_formation_eV": {"providers": ["external"]}},
            "targets": {
                molecule.candidate.id: {"enthalpy_formation_eV": {"record": local.record_id}}
            },
        }
    )
    selected = run((atom, molecule, local), request)
    assert selected.thermochemical_calculations["split"]["delta_h_eV"].value == -3.0
    assert selected.thermochemical_calculations["split"]["delta_g_eV"].status == "computed"
    assert request.for_quantity("enthalpy_formation_eV", atom.candidate.id).providers == (
        "external",
    )


def test_target_only_case_round_trip_and_saved_request(tmp_path: Path):
    state = candidate_state({"Ar": 1}, 0)
    prop = Property(1, "eV", tier="reviewed", provenance=SourceRef(provider="local_lab"))
    record = StateRecord(
        state.id, state, record_id="local:enthalpy", properties={"enthalpy_formation_eV": prop}
    )
    request = DataSelection.from_document(
        {"targets": {state.id: {"enthalpy_formation_eV": {"record": record.record_id}}}}
    )
    case = Case("argon", ("Ar",), data_selection=request)
    assert Case.from_document(case.document()).data_selection == request
    result = analyze(case, EvidenceCatalog(state_records=(record,)))
    export.write(tmp_path, result)
    saved = export.read(tmp_path, verify_views=True)
    assert saved["input"]["data_selection"] == request.document()


@pytest.mark.parametrize(
    ("target", "quantity"),
    [("not-a-candidate", "enthalpy_formation_eV"), ("Ar@ground", "rate_coefficient")],
)
def test_unused_or_wrong_target_kind_is_an_analysis_input_error(target, quantity):
    request = DataSelection.from_document(
        {"targets": {target: {quantity: {"providers": ["local"]}}}}
    )
    with pytest.raises(ValueError, match="data_selection target"):
        analyze(Case("argon", ("Ar",), data_selection=request), EvidenceCatalog())


def test_reaction_target_selection_keeps_other_reaction_candidates_independent():
    from reactgen.records import NumericDataset, Validity

    case = Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=300))
    generated = analyze(case, EvidenceCatalog())
    first, second = list(generated.candidates.reactions)[:2]
    dataset = NumericDataset(
        "external:rate",
        "rate_coefficient",
        "constant",
        unit="m3/s",
        observable="reaction_rate",
        params={"value": 1e-16},
        tier="reviewed",
        validity=Validity("gas_temperature", 200, 400, "K"),
        provenance=SourceRef(provider="external"),
    )
    local = replace(
        dataset, id="local:rate", params={"value": 2e-16}, provenance=SourceRef(provider="local")
    )
    request = DataSelection.from_document(
        {"targets": {first: {"rate_coefficient": {"record": local.id}}}}
    )
    other = replace(dataset, id="external:other-reaction-rate")
    selected = analyze(
        replace(case, data_selection=request),
        EvidenceCatalog(overlay_datasets={first: (dataset, local), second: (other,)}),
    )
    assert selected.evaluation.data_use[first].dataset_id == local.id
    assert selected.evaluation.data_use[second].dataset_id == other.id
    assert selected.evaluation.data_use[first].selection == request.document()
