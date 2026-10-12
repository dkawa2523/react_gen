"""Saved summaries explain responsibilities without changing scientific conclusions."""

from __future__ import annotations

import csv
import hashlib
from copy import deepcopy
from io import StringIO
from pathlib import Path

import pytest

from reactgen import export, needs, yamlio
from reactgen.case import Case
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze


def saved() -> dict:
    return export.document(analyze(Case("analysis", ("Ar",)), EvidenceCatalog.load(None)))


def test_grouped_needs_are_bounded_deterministic_and_keep_every_saved_finding() -> None:
    document = saved()
    before = deepcopy(document)
    compact = needs.build(document)
    full = needs.build(document, detail=True)
    assert "details" not in compact
    assert compact == {
        name: value for name, value in full.items() if name not in {"details", "work_details"}
    }
    assert sum(group["count"] for group in compact["needs"]) == len(full["details"])
    assert compact["summary"]["findings"] == len(full["details"])
    assert len(compact["needs"]) < len(full["details"])
    assert all("id" not in group for group in compact["needs"])
    assert all(len(group["target_examples"]) <= 3 for group in compact["needs"])
    assert all("@" not in item["target"] for item in full["details"])
    assert document == before
    document["states"].reverse()
    document["reactions"].reverse()
    assert needs.build(document, detail=True) == full


def test_csv_keeps_formation_reference_separate_from_the_input_gas_temperature() -> None:
    document = saved()
    document["input"]["conditions"]["gas_temperature_K"] = 700
    document["reactions"][0]["thermochemistry"].update(
        delta_h_eV=1, delta_h_reference_temperature_K=298.15, delta_h_standard_pressure_Pa=100000
    )
    table = export.csv_views(document)["reactions.csv"]
    row = next(csv.DictReader(StringIO(table)))
    assert row["delta_h_eV"] == "1"
    assert row["delta_h_reference_temperature_K"] == "298.15"
    assert row["delta_h_standard_pressure_Pa"] == "100000"
    document["metadata"].pop("helper_view_format")
    old_table = export.csv_views(document)["reactions.csv"]
    assert "delta_h_reference_temperature_K" not in next(csv.DictReader(StringIO(old_table)))


def test_source_information_models_and_scalar_inputs_are_different_work() -> None:
    document = saved()
    reaction = document["reactions"][0]
    reaction["data_use"].update(
        status="needs_input",
        required_inputs=[
            "gas_temperature",
            "dataset_applicability_conditions",
            "electron_energy_distribution",
            "rate_law_selection",
            "unknown_quantity",
        ],
        required_transforms=["eedf_integration"],
    )
    details = [
        row
        for row in needs.build(document, detail=True)["details"]
        if row["id"] == reaction["id"] and row["judgment"] == "data_use"
    ]
    tasks = {row["responsibility"]: row["requirements"] for row in details}
    assert tasks == {
        "user_inputs": ["conditions.gas_temperature_K"],
        "source_information": ["dataset_applicability_conditions"],
        "source_selection": ["data_selection"],
        "external_models": ["electron_energy_distribution"],
        "unsupported_inputs": ["unknown_quantity"],
        "transforms": ["eedf_integration"],
    }
    tables = export.csv_views(document)
    row = next(
        row
        for row in csv.DictReader(StringIO(tables["reactions.csv"]))
        if row["id"] == reaction["id"]
    )
    assert row["user_inputs"] == "conditions.gas_temperature_K"
    assert row["source_information"] == "dataset_applicability_conditions"
    assert row["external_models"] == "electron_energy_distribution"


def test_failure_is_not_reported_as_a_missing_fact_or_source_repair() -> None:
    document = saved()
    reaction = document["reactions"][0]
    judgment = reaction["assessments"]["thermochemistry"]
    judgment.update(verdict="fail", proposition="synthetic_energy_relation", message="inconsistent")
    group = next(
        row
        for row in needs.build(document)["needs"]
        if row["proposition"] == "synthetic_energy_relation"
    )
    assert group["status"] == "fail"
    assert group["responsibility"] == "failed_proposition"
    assert "repair" not in group["responsibility"]


def test_dataset_exclusions_and_reference_only_data_remain_inspectable() -> None:
    document = saved()
    reaction = document["reactions"][0]
    reaction["data_use"]["datasets"] = [
        {"dataset_id": "curve", "status": "reference_only", "reason": "no table"},
        {"dataset_id": "cold", "status": "out_of_range", "reason": "wrong temperature"},
        {"dataset_id": "broken", "status": "invalid", "reason": "wrong unit"},
    ]
    rows = {
        row["id"]: row
        for row in needs.build(document, detail=True)["details"]
        if row["subject"] == "dataset"
    }
    assert rows["curve"]["responsibility"] == "source_information"
    assert rows["curve"]["requirements"] == ["numerical_representation"]
    assert rows["cold"]["responsibility"] == "excluded_data"
    assert rows["broken"]["responsibility"] == "source_review"
    assert all(row["reaction_id"] == reaction["id"] for row in rows.values())


def test_csv_exposes_each_named_proposition_and_exact_saved_explanation() -> None:
    document = saved()
    assert document["metadata"]["helper_view_format"] == 3
    for subject, columns in (
        ("states", export.STATE_JUDGMENTS),
        ("reactions", export.REACTION_JUDGMENTS),
    ):
        rows = {
            row["id"]: row
            for row in csv.DictReader(StringIO(export.csv_views(document)[f"{subject}.csv"]))
        }
        for item in document[subject]:
            for name in columns:
                assert (
                    rows[item["id"]][f"{name}_proposition"]
                    == item["assessments"][name]["proposition"]
                )
                assert rows[item["id"]][f"{name}_reason"] == item["assessments"][name]["message"]
                assert rows[item["id"]][f"{name}_scope"] == item["assessments"][name]["scope"]


def test_historical_table_hashes_and_saved_conclusions_stay_readable(tmp_path: Path) -> None:
    document = saved()
    del document["metadata"]["helper_view_format"]
    tables = export.csv_views(document)
    assert (
        tuple(csv.DictReader(StringIO(tables["states.csv"])).fieldnames or ())
        == export.STATE_COLUMNS
    )
    assert (
        tuple(csv.DictReader(StringIO(tables["reactions.csv"])).fieldnames or ())
        == export.REACTION_COLUMNS
    )
    document["helper_views"] = {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in tables.items()
    }
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")
    export.rebuild_views(document, tmp_path)
    before = path.read_bytes()
    assert export.read(tmp_path, verify_views=True) == document
    export.rebuild_views(export.read(tmp_path), tmp_path)
    assert path.read_bytes() == before
    assert export.read(tmp_path, verify_views=True) == document
    document["states"][0]["assessments"]["thermochemistry"]["message"] = "changed conclusion"
    with pytest.raises(ValueError, match="helper view hashes"):
        export.validate(document)


def test_current_table_hashes_include_reaction_proposition_and_explanation() -> None:
    document = saved()
    document["reactions"][0]["assessments"]["thermochemistry"]["message"] = "changed explanation"
    with pytest.raises(ValueError, match="helper view hashes"):
        export.validate(document)


def test_needs_cli_detail_is_an_explicit_optional_view(tmp_path: Path, capsys) -> None:
    export.write(tmp_path, analyze(Case("analysis", ("Ar",)), EvidenceCatalog.load(None)))
    assert main(["needs", str(tmp_path)]) == 0
    compact = yamlio.load(capsys.readouterr().out)
    assert "details" not in compact
    assert main(["needs", str(tmp_path), "--detail"]) == 0
    detailed = yamlio.load(capsys.readouterr().out)
    assert len(detailed["details"]) == compact["summary"]["findings"]
