"""Record rejection, conflict and unavailable numbers are different work causes."""

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from reactgen import export, outcomes
from reactgen.assessment import assess_kinetics
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.generate import candidates
from reactgen.numeric import data_use
from reactgen.pipeline import analyze
from reactgen.records import NumericDataset, ReactionRecord, normalized_dataset


def source(tmp_path: Path, form: str, status: str) -> NumericDataset:
    path = tmp_path / "rate.csv"
    path.write_text("temperature_K,rate_m3_s\n300,1e-15\n1000,1e-15\n", encoding="utf-8")
    return normalized_dataset(
        {
            "id": "source",
            "kind": "rate_coefficient",
            "form": form,
            "status": status,
            "unit": "m3/s",
            "observable": "reaction_rate",
            "independent_variable": "gas_temperature",
            "parameters": {"value": 1e-15},
            "asset": {"path": path.name},
            "validity": {
                "quantity": "gas_temperature",
                "minimum": 300,
                "maximum": 1000,
                "unit": "K",
            },
        },
        base=tmp_path,
    )


def elastic_channel():
    return next(
        reaction
        for reaction in candidates(("Ar",)).reactions.values()
        if reaction.family == "electron" and reaction.process == "elastic"
    )


@pytest.mark.parametrize("form", ["reference_only", "constant", "table"])
@pytest.mark.parametrize(
    ("status", "native_label", "verdict", "claim_label"),
    [
        ("rejected", "excluded", "fail", "not_satisfied"),
        ("conflicting", "conflicting_data", "unknown", "review_required"),
    ],
)
def test_record_status_has_the_same_meaning_before_and_after_number_acquisition(
    tmp_path: Path, form: str, status: str, native_label: str, verdict: str, claim_label: str
) -> None:
    record = source(tmp_path, form, status)
    evidence = ReactionEvidence(overlay_datasets=(record,))
    claim, use = assess_kinetics(elastic_channel(), evidence, Conditions(gas_temperature_K=350))
    native = use.datasets[0]
    assert outcomes.numerical_outcome(asdict(native))["label"] == native_label
    assert outcomes.numerical_outcome(asdict(use))["label"] == (
        "excluded" if status == "rejected" else "conflicting_data"
    )
    assert claim.verdict == verdict
    assert outcomes.assessment_outcome(asdict(claim), {}, asdict(use))["label"] == claim_label
    assert {(item.responsibility, item.quantity) for item in native.requirements} == {
        ("source_review", "record_status")
    }
    assert not any(item.responsibility == "source_information" for item in use.requirements)


def test_active_reference_without_numbers_remains_missing_data(tmp_path: Path) -> None:
    record = source(tmp_path, "reference_only", "reviewed")
    use = data_use(elastic_channel(), ReactionEvidence(overlay_datasets=(record,)), Conditions())
    assert outcomes.numerical_outcome(asdict(use))["label"] == "data_missing"


def test_an_excluded_record_is_not_a_prerequisite_to_completing_an_independent_reference(
    tmp_path: Path,
) -> None:
    excluded = source(tmp_path, "constant", "rejected")
    reference = replace(source(tmp_path, "reference_only", "reviewed"), id="reference")
    use = data_use(
        elastic_channel(),
        ReactionEvidence(overlay_datasets=(excluded, reference)),
        Conditions(gas_temperature_K=350),
    )
    assert outcomes.numerical_outcome(asdict(use))["label"] == "data_missing"
    assert {item.target for item in use.requirements} == {reference.id}


@pytest.mark.parametrize("form", ["reference_only", "constant", "table"])
@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_stopped_source_does_not_remove_an_independent_usable_coefficient(
    tmp_path: Path, form: str, status: str
) -> None:
    stopped = source(tmp_path, form, status)
    active = replace(source(tmp_path, "constant", "reviewed"), id="independent")
    reaction = elastic_channel()
    inputs = Conditions(gas_temperature_K=350)
    first = data_use(reaction, ReactionEvidence(overlay_datasets=(stopped, active)), inputs)
    second = data_use(reaction, ReactionEvidence(overlay_datasets=(active, stopped)), inputs)
    assert first == second
    assert first.status == "coefficient"
    assert first.dataset_id == active.id
    assert first.value == 1e-15
    assert first.requirements == ()
    assert (stopped.id in first.disagreements) == (status == "conflicting")


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_status_and_work_meanings_survive_result_storage(tmp_path: Path, status: str) -> None:
    record = source(tmp_path, "reference_only", status)
    reaction = elastic_channel()
    result = analyze(
        Case("status", ("Ar",)),
        EvidenceCatalog(overlay_datasets={reaction.id: (record,)}),
    )
    export.write(tmp_path / "result", result)
    saved = export.read(tmp_path / "result")
    held = next(item for item in saved["reactions"] if item["id"] == reaction.id)
    assert held["data_use"]["datasets"][0]["label"] == (
        "excluded" if status == "rejected" else "conflicting_data"
    )
    assert held["assessments"]["kinetics"]["label"] == (
        "not_satisfied" if status == "rejected" else "review_required"
    )


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_containing_record_status_applies_without_rewriting_the_numerical_declaration(
    tmp_path: Path, status: str
) -> None:
    record = source(tmp_path, "constant", "reviewed")
    reaction = elastic_channel()
    parent = ReactionRecord(
        "parent",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        datasets=(record,),
        status=status,
    )
    use = data_use(reaction, ReactionEvidence((parent,)), Conditions(gas_temperature_K=350))
    assert use.datasets[0].status == ("invalid" if status == "rejected" else "conflict")
    assert use.value is None
    assert {item.target for item in use.requirements} == {parent.id}
    assert record.status == "reviewed"
    assert parent.datasets == (record,)


@pytest.mark.parametrize("independent_offer", ["overlay", "record"])
def test_an_independent_offer_of_the_same_number_survives_a_stopped_parent(
    tmp_path: Path, independent_offer: str
) -> None:
    record = source(tmp_path, "constant", "reviewed")
    reaction = elastic_channel()
    stopped = ReactionRecord(
        "stopped",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        datasets=(record,),
        status="conflicting",
    )
    evidence = (
        ReactionEvidence((stopped,), overlay_datasets=(record,))
        if independent_offer == "overlay"
        else ReactionEvidence((stopped, replace(stopped, id="independent", status="reviewed")))
    )
    use = data_use(reaction, evidence, Conditions(gas_temperature_K=350))
    assert use.status == "coefficient"
    assert use.value == 1e-15
    assert use.requirements == ()
    assert evidence.records[0].status == "conflicting"


def test_older_coefficient_labels_are_read_without_reprojection(tmp_path: Path) -> None:
    record = source(tmp_path, "constant", "rejected")
    reaction = elastic_channel()
    result = analyze(
        Case("historical", ("Ar",)),
        EvidenceCatalog(overlay_datasets={reaction.id: (record,)}),
    )
    historical = export.document(result)
    historical["metadata"]["helper_view_format"] = 5
    outcomes.add_labels(historical["states"], historical["reactions"], coefficient_exclusions=False)
    historical["summary"] = export.summary(historical["states"], historical["reactions"])
    historical["helper_views"] = {
        name: sha256(content.encode("utf-8")).hexdigest()
        for name, content in export.csv_views(historical).items()
    }
    held = next(item for item in historical["reactions"] if item["id"] == reaction.id)
    assert held["data_use"]["label"] == "review_required"
    export.validate(historical)
    assert held["data_use"]["label"] == "review_required"
