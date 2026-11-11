"""Related physical targets remain inspectable without entering exact-state conclusions."""

from copy import deepcopy
from dataclasses import replace

import pytest

from reactgen import export, yamlio
from reactgen.case import Case, Limits
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.presentation import registered_records
from reactgen.records import FormationReference, Property, StateRecord
from reactgen.selection import DataSelection


def records():
    composition = {"C": 2, "H": 6, "O": 1}
    targets = [
        candidate_state(composition, 0, "ground", resolution="resolved", **identity)
        for identity in ({}, {"structure": "source-structure"}, {"phase": "solid"})
    ]
    reference = FormationReference(298.15, "standard_elements", 100000)
    return tuple(
        StateRecord(
            target.id,
            target,
            record_id=identifier,
            properties={
                "enthalpy_formation_eV": Property(
                    value,
                    "eV",
                    tier="reviewed",
                    formation_reference=reference,
                )
            },
            source_declaration={
                "original_identity": identifier,
                "source_note": "retained verbatim",
            },
        )
        for target, identifier, value in zip(
            targets, ("generic", "structure-specific", "other-phase"), (1, 2, 3), strict=True
        )
    )


@pytest.mark.parametrize("generic_exact", [False, True])
def test_related_sources_are_retained_without_changing_existing_conclusions(
    tmp_path, generic_exact
):
    generic, structured, other_phase = records()
    initial = (generic,) if generic_exact else (structured,)
    additions = (structured, other_phase) if generic_exact else (other_phase,)
    case = Case(
        "formula target",
        ("C2H6O",),
        limits=Limits(max_atoms=9, max_depth=1, max_species=16, max_reactions=24),
    )
    baseline = analyze(case, EvidenceCatalog(state_records=initial))
    enriched = analyze(case, EvidenceCatalog(state_records=initial + additions))
    for field in (
        "state_assessments",
        "reaction_assessments",
        "thermochemistry",
        "thermochemical_calculations",
        "data_use",
    ):
        assert getattr(enriched.evaluation, field) == getattr(baseline.evaluation, field)
    evidence = enriched.evaluation.state_evidence[generic.candidate.id]
    assert evidence.match == ("exact" if generic_exact else "compatible")
    assert {record.record_id for record in evidence.records} == {
        "generic" if generic_exact else "structure-specific"
    }
    assert {record.record_id for record in evidence.related_records} == {
        record.record_id for record in additions
    }
    result_path = tmp_path / "result"
    export.write(result_path, enriched)
    document = export.read(result_path, verify_views=True)
    state = next(row for row in document["states"] if row["id"] == generic.candidate.id)
    assert {record["record_id"] for record in state["evidence"]["related_records"]} == {
        record.record_id for record in additions
    }
    listing = registered_records(document, generic.candidate.id, "enthalpy_formation_eV")
    listed = {record["record_id"]: record for record in listing["records"]}
    assert listed[initial[0].record_id]["target_match"] == evidence.match
    for record in additions:
        saved = listed[record.record_id]
        assert saved["target_match"] == "related"
        assert saved["record_target"] == record.candidate.id
        assert saved["phase"] == record.candidate.phase
        assert saved["structure"] == record.candidate.structure
    detail = registered_records(document, generic.candidate.id, detail=True)
    for record in additions:
        saved = next(row for row in detail["records"] if row["record_id"] == record.record_id)
        assert saved["source_declaration"] == record.source_declaration
    if generic_exact:
        request = DataSelection.from_document(
            {
                "targets": {
                    generic.candidate.id: {
                        "enthalpy_formation_eV": {"record": structured.record_id}
                    }
                }
            }
        )
        selected = analyze(
            replace(case, data_selection=request),
            EvidenceCatalog(state_records=initial + additions),
        )
        outcome = selected.evaluation.state_assessments[generic.candidate.id]["thermochemistry"]
        assert outcome.verdict == "unknown"
        assert any(work.responsibility == "source_selection" for work in outcome.requirements)


def test_other_phase_only_is_visible_but_does_not_supply_the_requested_gas_state(tmp_path):
    generic, _structured, other_phase = records()
    catalog = EvidenceCatalog(state_records=(other_phase,))
    evidence = catalog.state(generic.candidate)
    assert evidence.match == "none"
    assert not evidence.records
    assert evidence.related_records == (other_phase,)
    assert not evidence.sources
    case = Case(
        "gas target",
        ("C2H6O",),
        limits=Limits(max_atoms=9, max_depth=1, max_species=16, max_reactions=24),
    )
    baseline, related = analyze(case, EvidenceCatalog()), analyze(case, catalog)
    assert baseline.evaluation.state_assessments == related.evaluation.state_assessments
    document = export.document(related)
    # Historical files omit the new field; inspection does not invent lost records.
    for state in document["states"]:
        state["evidence"].pop("related_records")
        for record in state["evidence"]["records"]:
            record.pop("target_match", None)
    original = deepcopy(document)
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")
    assert export.read(path) == original
    assert not registered_records(original, generic.candidate.id)["records"]
