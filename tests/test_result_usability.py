"""Saved summaries explain responsibilities without changing scientific conclusions."""

from __future__ import annotations

import csv
import hashlib
from copy import deepcopy
from dataclasses import asdict
from io import StringIO
from pathlib import Path

import pytest

from reactgen import export, needs, yamlio
from reactgen.case import Case, Conditions, Limits
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.model import numerical_requirements
from reactgen.pipeline import analyze


def saved() -> dict:
    return export.document(
        analyze(
            Case("analysis", ("Ar",), limits=Limits(max_atoms=1, max_depth=1)),
            EvidenceCatalog.load(None),
        )
    )


def test_cli_assesses_requested_equations_without_supplying_or_expanding_their_states(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "case.yaml"
    input_path.write_text(
        "gases: [Ar]\nsupplies: [e]\nlimits: {max_atoms: 1, max_depth: 1}\n"
        "reactions:\n"
        "- {equation: 'e + Ar -> Ar+ + 2 e', process: ionization}\n"
        "- {equation: 'e + Ar+ -> Ar^2+ + 2 e', process: ionization}\n"
        "- {equation: 'e + Ne^2+ -> Ne^3+ + 2 e', process: ionization}\n"
        "- {equation: 'e + Ar -> Ar+ + e', process: ionization}\n",
        encoding="utf-8",
    )
    directory = tmp_path / "result"
    assert main(["analyze", "--input", str(input_path), "--out", str(directory)]) == 1
    assert "Requested reactions: 4" in capsys.readouterr().out
    document = export.read(directory, verify_views=True)
    requested = Case.load(input_path).reactions
    reactions = {item["id"]: item for item in document["reactions"]}
    requested_ids = {item.candidate.id for item in requested}
    baseline_ids = {item["id"] for item in saved()["reactions"]}
    assert set(reactions) == requested_ids | baseline_ids
    assert document["pathways"]["seeds"] == ["Ar@ground", "e"]
    reached = document["pathways"]["conditioned"]["state_layers"]
    assert "Ar^2+@ground" in reached
    assert "Ne^3+@ground" not in reached
    admitted = [reactions[identifier] for identifier in requested_ids - baseline_ids]
    assert all(item["origin"] == "requested" for item in admitted)
    assert all(
        item["assessments"]["reaction_evidence"]["verdict"] == "unknown" for item in admitted
    )
    assert any(item["assessments"]["conservation"]["verdict"] == "fail" for item in admitted)


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
    assert all(len(group["target_examples"]) <= 3 for group in compact["needs"])
    assert all("@" not in item["target"] for item in full["details"])
    assert document == before
    document["states"].reverse()
    document["reactions"].reverse()
    assert needs.build(document, detail=True) == full


def test_csv_keeps_formation_reference_separate_from_the_input_gas_temperature() -> None:
    document = saved()
    document["input"]["conditions"]["gas_temperature_K"] = 700
    reaction = document["reactions"][0]
    reaction["thermochemistry"].update(
        delta_h_eV=1, delta_h_reference_temperature_K=298.15, delta_h_standard_pressure_Pa=100000
    )
    tables = export.csv_views(document)
    row = next(
        row
        for row in csv.DictReader(StringIO(tables["judgments/thermochemistry.csv"]))
        if row["id"] == reaction["id"]
    )
    assert row["delta_h_eV"] == "1"
    assert row["delta_h_reference_temperature_K"] == "298.15"
    assert row["delta_h_standard_pressure_Pa"] == "100000"
    assert "delta_h_eV" not in next(csv.DictReader(StringIO(tables["reactions.csv"])))
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
    use = reaction["data_use"]
    use["requirements"] = [
        asdict(item)
        for item in numerical_requirements(
            use["required_inputs"], use["required_transforms"], reaction["id"], use["reason"]
        )
    ]
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
        for row in csv.DictReader(StringIO(tables["judgments/kinetics.csv"]))
        if row["id"] == reaction["id"]
    )
    steps = row["next_steps"].split(" | ")
    for responsibility, quantities in tasks.items():
        for quantity in quantities:
            assert any(quantity in step and responsibility in step for step in steps)


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


def test_work_summary_respects_collision_pair_applicability() -> None:
    document = export.document(
        analyze(
            Case(
                "scoped",
                ("Ar", "F"),
                Conditions(collision_energy_eV=3, collision_energy_frame="com", target_state="Ar"),
                limits=Limits(max_atoms=1, max_depth=1),
                supplies=("e",),
            ),
            EvidenceCatalog.load(None),
        )
    )
    outside = next(
        row
        for row in document["reactions"]
        if row["assessments"]["energy"]["verdict"] == "not_applicable"
        and "collision_energy_margin_eV" in row["thermochemical_calculations"]
    )
    details = needs.build(document, detail=True)["details"]
    assert not any(
        row["id"] == outside["id"] and row["judgment"] == "calculation:collision_energy_margin_eV"
        for row in details
    )


def test_dataset_exclusions_and_reference_only_data_remain_inspectable() -> None:
    document = saved()
    reaction = document["reactions"][0]
    reaction["data_use"]["datasets"] = [
        {
            "dataset_id": "curve",
            "status": "reference_only",
            "reason": "no table",
            "scope": "native curve",
            "requirements": [
                {
                    "responsibility": "source_information",
                    "target": "curve",
                    "quantity": "numerical_representation",
                    "reason": "no table",
                }
            ],
        },
        {
            "dataset_id": "cold",
            "status": "out_of_range",
            "reason": "wrong temperature",
            "scope": "native point",
            "requirements": [],
        },
        {
            "dataset_id": "broken",
            "status": "invalid",
            "reason": "wrong unit",
            "scope": "native point",
            "requirements": [
                {
                    "responsibility": "source_review",
                    "target": "broken",
                    "quantity": "numerical_record",
                    "reason": "wrong unit",
                }
            ],
        },
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
    assert document["metadata"]["helper_view_format"] == export.FOCUSED_VIEW_FORMAT
    tables = export.csv_views(document)
    for subject in ("states", "reactions"):
        for name in document["summary"]["judgments"][subject]:
            if subject == "reactions":
                stem = name
            else:
                stem = "state-support" if name == "state" else f"state-{name}"
            rows = {
                row["id"]: row for row in csv.DictReader(StringIO(tables[f"judgments/{stem}.csv"]))
            }
            claims = {
                item["id"]: item["assessments"][name]
                for item in document[subject]
                if name in item["assessments"]
            }
            assert rows.keys() == claims.keys()
            for identifier, claim in claims.items():
                row = rows[identifier]
                assert row["proposition"] == claim["proposition"]
                assert row["reason"] == claim["message"]
                assert row["scope"] == claim["scope"]


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


def test_csv_extracts_one_saved_judgment_without_replacing_full_views(
    tmp_path: Path, capsys
) -> None:
    case = Case(
        "ground argon at zero relative energy",
        ("Ar",),
        conditions=Conditions(collision_energy_eV=0, collision_energy_frame="com"),
        limits=Limits(max_atoms=1, max_depth=1),
        supplies=("e",),
    )
    registry = Path(__file__).resolve().parents[1] / "registry"
    document = export.write(tmp_path, analyze(case, EvidenceCatalog.load(registry)))
    expected = {
        reaction["id"]: reaction
        for reaction in document["reactions"]
        if reaction["assessments"]["energy"]["verdict"] == "fail"
    }
    assert any(reaction["process"] == "ionization" for reaction in expected.values())
    assert any(
        reaction["assessments"]["energy"]["verdict"] == "pass" for reaction in document["reactions"]
    )
    arguments = ["view", str(tmp_path), "--kind", "csv", "--out", str(tmp_path)]
    assert main([*arguments, "--judgment", "energy", "--verdict", "fail"]) == 0
    with (tmp_path / "energy.filtered.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["id"] for row in rows} == expected.keys()
    for row in rows:
        reaction = expected[row["id"]]
        claim = reaction["assessments"]["energy"]
        assert row["verdict"] == "fail"
        assert (row["family"], row["process"]) == (reaction["family"], reaction["process"])
        assert (row["proposition"], row["scope"], row["reason"]) == (
            claim["proposition"],
            claim["scope"],
            claim["message"],
        )
    assert export.read(tmp_path, verify_views=True) == document
    assert (
        main(
            [
                *arguments,
                "--process",
                "ionization",
                "--require",
                "conservation=pass",
                "--require",
                "energy=fail",
            ]
        )
        == 0
    )
    with (tmp_path / "reactions.filtered.csv").open(encoding="utf-8", newline="") as stream:
        filtered = {row["id"] for row in csv.DictReader(stream)}
    assert filtered == {
        identifier
        for identifier, reaction in expected.items()
        if reaction["process"] == "ionization"
        and reaction["assessments"]["conservation"]["verdict"] == "pass"
    }
    assert filtered
    assert export.read(tmp_path, verify_views=True) == document
    assert main([*arguments, "--judgment", "unknown_key"]) == 2
    assert "available judgments:" in capsys.readouterr().err


def test_needs_cli_detail_is_an_explicit_optional_view(tmp_path: Path, capsys) -> None:
    export.write(tmp_path, analyze(Case("analysis", ("Ar",)), EvidenceCatalog.load(None)))
    assert main(["needs", str(tmp_path)]) == 0
    compact = yamlio.load(capsys.readouterr().out)
    assert "details" not in compact
    assert main(["needs", str(tmp_path), "--detail"]) == 0
    detailed = yamlio.load(capsys.readouterr().out)
    assert len(detailed["details"]) == compact["summary"]["findings"]
