"""The public request, selected number, and retained disagreement describe one use."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import export
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.records import NumericDataset, SourceRef, Validity
from reactgen.selection import DataSelection


def selected_result(equal_values: bool = False, mode: str = "prefer"):
    base = Case("sample", ("Ar",), conditions=Conditions(gas_temperature_K=300))
    generated = analyze(base, EvidenceCatalog())
    target = next(
        reaction
        for reaction in generated.candidates.reactions.values()
        if reaction.process == "ionization"
    )
    first = NumericDataset(
        "lab-a-rate",
        "rate_coefficient",
        "constant",
        unit="m3/s",
        observable="reaction_rate",
        params={"value": 1e-16},
        tier="reviewed",
        validity=Validity("gas_temperature", 200, 400, "K"),
        provenance=SourceRef(provider="lab_a"),
        method="measured",
    )
    second = replace(
        first,
        id="lab-b-rate",
        params={"value": 1e-16 if equal_values else 2e-16},
        provenance=SourceRef(provider="lab_b"),
    )
    request = DataSelection.from_document(
        {
            "quantities": {
                "rate_coefficient": {
                    "mode": mode,
                    "providers": ["lab_a"] if mode == "only" else ["lab_a", "lab_b"],
                }
            }
        }
    )
    result = analyze(
        replace(base, data_selection=request),
        EvidenceCatalog(overlay_datasets={target.id: (first, second)}),
    )
    return target.id, result


def test_cli_api_shape_and_saved_number_share_the_selection(tmp_path: Path) -> None:
    target, result = selected_result()
    export.write(tmp_path, result)
    document = export.read(tmp_path, verify_views=True)
    request = document["input"]["data_selection"]
    assert Case.from_document(document["input"]).data_selection.document() == request
    reaction = next(item for item in document["reactions"] if item["id"] == target)
    use = reaction["data_use"]
    assert use["dataset_id"] == "lab-a-rate"
    assert use["value"] == pytest.approx(1e-16)
    assert use["selection"] == request
    assert use["disagreements"] == ["lab-b-rate"]
    assert reaction["assessments"]["reaction_evidence"]["verdict"] == "unknown"
    assert reaction["assessments"]["kinetics"]["verdict"] == "pass"
    assert "source_declaration" in reaction["evidence"]["overlay_datasets"][0]


def test_saved_disagreement_must_refer_to_a_dataset() -> None:
    target, result = selected_result()
    document = export.document(result)
    reaction = next(item for item in document["reactions"] if item["id"] == target)
    reaction["data_use"]["disagreements"] = ["not-a-dataset"]
    with pytest.raises(ValueError, match="disagreement"):
        export.validate(document)


def test_saved_selection_must_match_the_analysis_request() -> None:
    target, result = selected_result()
    document = export.document(result)
    reaction = next(item for item in document["reactions"] if item["id"] == target)
    reaction["data_use"]["selection"] = {}
    with pytest.raises(ValueError, match="selection contradicts analysis request"):
        export.validate(document)


def test_duplicate_dataset_identity_conflict_can_be_saved(tmp_path: Path) -> None:
    target, result = selected_result()
    offered = result.evaluation.reaction_evidence[target].overlay_datasets
    same_id = (offered[0], replace(offered[1], id=offered[0].id))
    result = analyze(
        Case("sample", ("Ar",), conditions=Conditions(gas_temperature_K=300)),
        EvidenceCatalog(overlay_datasets={target: same_id}),
    )
    export.write(tmp_path, result)
    document = export.read(tmp_path, verify_views=True)
    item = next(reaction for reaction in document["reactions"] if reaction["id"] == target)
    assert item["data_use"]["status"] == "conflict"
    assert item["data_use"]["disagreements"] == ["lab-a-rate"]
    assert item["assessments"]["reaction_evidence"]["basis"] == ["lab-a-rate"]


@pytest.mark.parametrize("mode", ["prefer", "only"])
def test_saved_equal_value_does_not_bypass_the_source_request(mode: str) -> None:
    target, result = selected_result(equal_values=True, mode=mode)
    document = export.document(result)
    reaction = next(item for item in document["reactions"] if item["id"] == target)
    reaction["data_use"]["dataset_id"] = "lab-b-rate"
    with pytest.raises(ValueError, match="restrictions|priority"):
        export.validate(document)


def test_saved_kind_must_describe_the_selected_scientific_record() -> None:
    target, result = selected_result()
    result = analyze(
        Case("sample", ("Ar",)),
        EvidenceCatalog(
            overlay_datasets={
                target: result.evaluation.reaction_evidence[target].overlay_datasets[:1]
            }
        ),
    )
    document = export.document(result)
    reaction = next(item for item in document["reactions"] if item["id"] == target)
    assert reaction["data_use"]["status"] == "needs_input"
    reaction["data_use"]["kind"] = "sticking_coefficient"
    with pytest.raises(ValueError, match="quantity contradicts"):
        export.validate(document)
