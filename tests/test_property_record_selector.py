"""A record ID shown in a result selects the same retained scientific declaration."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import export
from reactgen.case import Case
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.records import (
    FormationReference,
    Property,
    SourceRef,
    StateRecord,
    selectable_state_record_id,
)
from reactgen.selection import DataSelection


def records():
    atom, molecule = (candidate_state({"F": count}, 0) for count in (1, 2))
    reference = FormationReference(298.15, "standard_elements", 100000)
    return tuple(
        StateRecord(
            state.id,
            state,
            properties={
                "enthalpy_formation_eV": Property(
                    value,
                    "eV",
                    tier="reviewed",
                    formation_reference=reference,
                    provenance=SourceRef(provider=provider),
                )
            },
            provenance=SourceRef(provider=provider),
        )
        for state, value, provider in (
            (atom, 1, "external"),
            (molecule, 3, "external"),
            (molecule, 5, "local"),
        )
    )


def selected_delta_h(result):
    reaction = next(
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.process == "dissociation"
        and any(term.species == "F2@ground" for term in reaction.reactants)
        and any(term.species == "F@ground" and term.n == 2 for term in reaction.products)
    )
    return result.evaluation.thermochemical_calculations[reaction.id]["delta_h_eV"]


def test_anonymous_id_from_result_is_selectable_without_mutating_the_input_catalog(tmp_path: Path):
    initial = records()
    catalog = EvidenceCatalog(state_records=initial)
    base = Case("fluorine", ("F2",))
    listing = export.document(analyze(base, catalog))
    ground = next(state for state in listing["states"] if state["id"] == "F2@ground")
    chosen = next(
        record
        for record in ground["evidence"]["records"]
        if record["properties"]["enthalpy_formation_eV"]["value"] == 5
    )
    request = DataSelection.from_document(
        {"targets": {ground["id"]: {"enthalpy_formation_eV": {"record": chosen["record_id"]}}}}
    )
    selected = analyze(replace(base, data_selection=request), catalog)
    assert selected_delta_h(selected).value == -3
    assert all(record.record_id is None for record in catalog.state_records)
    export.write(tmp_path, selected)
    saved = export.read(tmp_path, verify_views=True)
    assert saved["input"]["data_selection"] == request.document()
    assert {record["record_id"] for record in ground["evidence"]["records"]} == {
        selectable_state_record_id(record) for record in initial[1:]
    }
    reloaded_catalog = EvidenceCatalog(
        state_records=tuple(
            replace(record, record_id=selectable_state_record_id(record)) for record in initial
        )
    )
    reloaded = analyze(replace(base, data_selection=request), reloaded_catalog)
    assert selected_delta_h(reloaded).value == -3


def test_a_target_selector_does_not_remove_another_species_value_or_change_its_state_claim():
    initial = records()
    request = DataSelection.from_document(
        {
            "targets": {
                "F2@ground": {
                    "enthalpy_formation_eV": {"record": selectable_state_record_id(initial[2])}
                }
            }
        }
    )
    case = Case("fluorine", ("F2",), data_selection=request)
    first = analyze(case, EvidenceCatalog(state_records=initial))
    enriched_atom = replace(
        initial[0], properties=initial[0].properties | {"mass_amu": Property(19, "amu")}
    )
    second = analyze(case, EvidenceCatalog(state_records=(enriched_atom, *initial[1:])))
    assert selected_delta_h(first) == selected_delta_h(second)
    for state_id in ("F@ground", "F2@ground"):
        assert (
            first.evaluation.state_assessments[state_id]["state"]
            == second.evaluation.state_assessments[state_id]["state"]
        )


def test_existing_canonical_record_ids_are_preserved():
    original = replace(records()[0], record_id="saved-legacy-id")
    assert selectable_state_record_id(original) == "saved-legacy-id"
    assert selectable_state_record_id(replace(original, properties={})) == "saved-legacy-id"


def test_native_source_identity_cannot_change_target_when_legacy_record_id_is_absent():
    first, second = (candidate_state({gas: 1}, 0) for gas in ("Ar", "Ne"))
    source = SourceRef(provider="local", collection="table", record_id="row1")
    declarations = tuple(
        StateRecord(state.id, state, provenance=source) for state in (first, second)
    )
    assert all(record.record_id is None for record in declarations)
    with pytest.raises(ValueError, match="different physical targets"):
        EvidenceCatalog(state_records=declarations)


def test_anonymous_legacy_declarations_without_native_ids_stay_separate_by_target():
    first, second = (candidate_state({gas: 1}, 0) for gas in ("Ar", "Ne"))
    declarations = tuple(StateRecord("legacy container", state) for state in (first, second))
    catalog = EvidenceCatalog(state_records=declarations)
    identifiers = {selectable_state_record_id(record) for record in catalog.state_records}
    assert len(identifiers) == 2
    assert all(record.record_id is None for record in catalog.state_records)
