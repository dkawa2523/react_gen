"""Missing scientific data never replace rejection or unrelated work causes."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from reactgen import export, needs, outcomes, yamlio
from reactgen.assessment import assess_reaction_evidence
from reactgen.case import Case
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.presentation import analysis_overview, registered_records
from reactgen.records import Property, StateRecord, selectable_state_record_id
from reactgen.selection import DataSelection


def saved() -> dict:
    return export.document(analyze(Case("coverage", ("Ar",)), EvidenceCatalog.load(None)))


def test_same_proposition_rejection_wins_over_missing_dependencies() -> None:
    state = {
        "assessments": {
            "state": {
                "verdict": "unknown",
                "requirements": [
                    {"responsibility": "source_information", "target": "s", "quantity": "existence"}
                ],
            }
        }
    }
    claim = {"verdict": "fail", "dependencies": [["s", "state"]]}
    assert outcomes.assessment_outcome(claim, {"s": state}) == {
        "label": "not_satisfied",
        "blocking_causes": [],
    }
    claim["verdict"] = "unknown"
    assert outcomes.assessment_outcome(claim, {"s": state}) == {
        "label": "data_missing",
        "blocking_causes": ["data_missing"],
    }


@pytest.mark.parametrize(
    ("role", "cause"),
    [
        ("source_information", "data_missing"),
        ("source_review", "review_required"),
        ("source_selection", "selection_required"),
        ("identity", "identity_unresolved"),
        ("user_inputs", "input_missing"),
        ("external_models", "model_unsupported"),
    ],
)
def test_unknown_work_causes_do_not_all_become_missing_data(role: str, cause: str) -> None:
    claim = {
        "verdict": "unknown",
        "requirements": [{"responsibility": role, "target": "s", "quantity": "q"}],
    }
    assert outcomes.assessment_outcome(claim, {}) == {
        "label": cause,
        "blocking_causes": [cause],
    }


def test_excluded_native_data_are_not_data_missing_or_reaction_rejection() -> None:
    record = {
        "status": "invalid",
        "requirements": [{"responsibility": "source_information", "target": "d", "quantity": "q"}],
    }
    assert outcomes.numerical_outcome(record) == {"label": "excluded", "blocking_causes": []}
    record["status"] = "out_of_range"
    assert outcomes.numerical_outcome(record) == {"label": "out_of_range", "blocking_causes": []}


@pytest.mark.parametrize(
    ("statuses", "label", "responsibility"),
    [
        (["invalid"], "excluded", "source_review"),
        (["out_of_range"], "out_of_range", "source_review"),
        (["invalid", "out_of_range"], "excluded", "source_review"),
        (["invalid", "unreviewed"], "review_required", "source_review"),
        (["invalid", "reference_only"], "data_missing", "source_information"),
    ],
)
def test_coefficient_exclusion_and_unresolved_work_are_distinct(
    statuses, label, responsibility
) -> None:
    use = {
        "status": "unavailable",
        "datasets": [{"status": status} for status in statuses],
        "requirements": [{"responsibility": responsibility, "target": "record", "quantity": "q"}],
    }
    assert outcomes.numerical_outcome(use) == {
        "label": label,
        "blocking_causes": [] if label in {"excluded", "out_of_range"} else [label],
    }


def test_missing_provenance_of_attested_channel_is_unknown_not_negative_evidence() -> None:
    reaction = ReactionCandidate(
        "r", (Term("A"),), (Term("B"),), "neutral", "dissociation", "attested_only", "source", 0
    )
    result = assess_reaction_evidence(reaction, ReactionEvidence())
    assert result.verdict == "unknown"
    assert result.requirements[0].responsibility == "source_information"
    assert result.proposition == "channel_evidence_support"


def test_result_reports_domain_denominators_and_completion_tasks() -> None:
    document = saved()
    coverage = document["summary"]["coverage"]
    consistency = coverage["judgments"]["reactions"]["consistency"]
    kinetics = coverage["judgments"]["reactions"]["kinetics"]
    assert consistency["data_missing"] == 0
    assert kinetics["data_missing"] == kinetics["applicable"]
    assert kinetics["data_missing_fraction"] == 1
    work = needs.build(document, detail=True, data_missing_only=True)
    assert work["coverage"] == coverage
    assert work["data_completion"]
    assert all("data_missing" in item["blocking_causes"] for item in work["details"])
    assert all(item["status"] != "fail" for item in work["details"])
    assert all(
        task["responsibility"] in {"source_information", "investigation"}
        for task in work["data_completion"]
    )
    assert "not satisfied:" in "\n".join(analysis_overview(document, work))


def test_failed_aggregate_is_not_an_affected_missing_data_conclusion() -> None:
    document = saved()
    reaction = next(
        item
        for item in document["reactions"]
        if item["assessments"]["state"]["verdict"] == "unknown"
    )
    reaction["assessments"]["state"]["verdict"] = "fail"
    outcomes.add_labels(document["states"], document["reactions"])
    document["summary"] = export.summary(document["states"], document["reactions"])
    work = needs.build(document, detail=True)
    for task in work["data_completion"]:
        assert not any(
            item["id"] == reaction["id"] and item["judgment"] == "state"
            for item in task["affected"]
        )


def test_label_and_count_tampering_is_rejected_without_scientific_reassessment() -> None:
    document = saved()
    edited = deepcopy(document)
    edited["states"][0]["assessments"]["consistency"]["label"] = "data_missing"
    with pytest.raises(ValueError, match="outcome label"):
        export.validate(edited)
    edited = deepcopy(document)
    edited["summary"]["coverage"]["judgments"]["states"]["state"]["data_missing"] += 1
    with pytest.raises(ValueError, match="summary contradicts"):
        export.validate(edited)


def test_historical_format4_reads_without_new_labels(tmp_path: Path, monkeypatch) -> None:
    document = saved()
    document["metadata"]["helper_view_format"] = 4
    for candidate in (*document["states"], *document["reactions"]):
        records = list(candidate["assessments"].values())
        if "data_use" in candidate:
            records += [
                candidate["data_use"],
                *candidate["data_use"]["datasets"],
                *candidate["thermochemical_calculations"].values(),
            ]
        for record in records:
            record.pop("label")
            record.pop("blocking_causes")
    document["summary"] = export.summary(document["states"], document["reactions"])
    document["helper_views"] = {
        name: hashlib.sha256(content.encode()).hexdigest()
        for name, content in export.csv_views(document).items()
    }
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("reading saved results must not evaluate evidence")

    monkeypatch.setattr("reactgen.assessment.evaluate", forbidden)
    assert export.read(path) == document
    with pytest.raises(ValueError, match="historical result"):
        needs.build(document, data_missing_only=True)


def test_anonymous_legacy_record_can_be_inspected_and_fixed_without_changing_it() -> None:
    state = candidate_state({"Ar": 1}, 0)
    record = StateRecord(
        state.id,
        state,
        properties={
            "ionization_energy_eV": Property(15.8, "eV", tier="reviewed", definition="atomic")
        },
    )
    catalog = EvidenceCatalog(state_records=(record,))
    baseline = export.document(analyze(Case("record", ("Ar",)), catalog))
    identifier = selectable_state_record_id(record)
    listing = registered_records(baseline, state.id, "ionization_energy_eV")
    assert listing["records"][0]["record_id"] == identifier
    assert "source_declaration" not in listing["records"][0]
    assert "source_declaration" in registered_records(baseline, state.id, detail=True)["records"][0]
    policy = DataSelection.from_document(
        {"targets": {state.id: {"ionization_energy_eV": {"record": identifier}}}}
    )
    selected = export.document(analyze(Case("record", ("Ar",), data_selection=policy), catalog))
    assert selected["summary"]["coverage"] == baseline["summary"]["coverage"]
    assert record.record_id is None
    assert selected["states"] == baseline["states"]
