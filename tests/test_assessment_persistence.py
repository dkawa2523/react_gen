"""Saved meaning, dependencies and concrete work stay consistent across views."""

from __future__ import annotations

import csv
import hashlib
from copy import deepcopy
from io import StringIO
from pathlib import Path

import pytest

from reactgen import export, needs, yamlio
from reactgen.case import Case, Limits
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.model import ReactionCandidate, Term, reaction_id
from reactgen.pipeline import analyze
from reactgen.records import StateRecord


def saved() -> dict:
    return export.document(
        analyze(
            Case("analysis", ("Ar",), limits=Limits(max_atoms=1, max_depth=1)),
            EvidenceCatalog.load(None),
        )
    )


def rehash(document: dict) -> None:
    document["helper_views"] = {
        name: hashlib.sha256(content.encode()).hexdigest()
        for name, content in export.csv_views(document).items()
    }


def test_binding_and_existence_have_distinct_owners_and_applicable_populations(
    tmp_path: Path,
) -> None:
    anion = candidate_state({"Ar": 1}, -1)
    occurrence = StateRecord(
        anion.id,
        anion,
        existence="confirmed",
        existence_source="test occurrence evidence",
        tier="reviewed",
    )
    analysis = analyze(
        Case("independent claims", ("Ar",), limits=Limits(max_atoms=1, max_depth=1)),
        EvidenceCatalog(state_records=(occurrence,)),
    )
    document = export.document(analysis)
    target = next(state for state in document["states"] if state["id"] == anion.id)
    assert target["assessments"]["state"]["proposition"] == "state_existence_support"
    assert target["assessments"]["state"]["verdict"] == "pass"
    assert target["assessments"]["electron_binding"]["verdict"] == "unknown"
    assert sum(document["summary"]["judgments"]["states"]["electron_binding"].values()) == 1
    population = document["summary"]["coverage"]["judgments"]["states"]["electron_binding"]
    assert population["total"] == 1
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")
    assert export.read(path) == document


def historical_fractional_duplicates(version: int) -> dict:
    document = saved()
    document["metadata"]["helper_view_format"] = version
    reaction = next(row for row in document["reactions"] if row["process"] == "elastic")
    old_identifier = reaction["id"]
    # The former sequential-float key encoded 0.1 + 0.2 as this serialized value.
    legacy_side = (("Ar@ground", 0.30000000000000004), ("e", 1.0))
    legacy_id = reaction_id(("electron", "elastic", None, None, None, legacy_side, legacy_side))
    terms = (Term("e"), Term("Ar@ground", 0.1), Term("Ar@ground", 0.2))
    candidate = ReactionCandidate(legacy_id, terms, terms, "electron", "elastic", "test", "test", 0)
    assert reaction_id(candidate.key) != legacy_id
    reaction["reactants"] = [term._asdict() for term in terms]
    reaction["products"] = [term._asdict() for term in terms]
    reaction["equation"] = candidate.equation

    def replace_reference(value):
        if isinstance(value, dict):
            return {key: replace_reference(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_reference(item) for item in value]
        return legacy_id if value == old_identifier else value

    document = replace_reference(document)
    rehash(document)
    return document


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_historical_fractional_duplicate_ids_and_view_hashes_are_read_without_rewriting(
    tmp_path: Path, version: int
) -> None:
    document = historical_fractional_duplicates(version)
    original = deepcopy(document)
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")
    for name, content in export.csv_views(document).items():
        (tmp_path / name).write_bytes(content.encode("utf-8"))
    assert export.read(path, verify_views=True) == original
    assert yamlio.load(path.read_text(encoding="utf-8")) == original


def test_current_format_rejects_the_historical_fractional_duplicate_hash() -> None:
    with pytest.raises(ValueError, match="reaction identity"):
        export.validate(historical_fractional_duplicates(6))


def test_individual_scope_requirements_and_dependencies_roundtrip(tmp_path: Path) -> None:
    document = saved()
    views = export.csv_views(document)
    by_judgment = {
        name: {row["id"]: row for row in csv.DictReader(StringIO(views[f"judgments/{name}.csv"]))}
        for name in document["summary"]["judgments"]["reactions"]
    }
    for reaction in document["reactions"]:
        for name, judgment in reaction["assessments"].items():
            row = by_judgment[name][reaction["id"]]
            assert row["scope"] == judgment["scope"]
            assert row["depends_on"] == " | ".join(
                f"{target} / {dependency}" for target, dependency in judgment["dependencies"]
            )
            source = reaction["data_use"] if name == "kinetics" else judgment
            steps = row["next_steps"].split(" | ") if row["next_steps"] else []
            assert len(steps) == len(source["requirements"])
            for step, requirement in zip(steps, source["requirements"], strict=True):
                assert all(value in step for value in requirement.values())
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")
    export.rebuild_views(document, tmp_path)
    assert export.read(path, verify_views=True) == document


@pytest.mark.parametrize("field", ["scope", "requirements", "dependencies"])
def test_current_hashes_cover_the_saved_meaning(field: str) -> None:
    document = saved()
    judgment = document["reactions"][0]["assessments"]["thermochemistry"]
    changes = {
        "scope": "a different declared model",
        "requirements": [
            {
                "responsibility": "source_information",
                "target": "Ar@ground",
                "quantity": "ionization_energy_eV",
                "reason": "missing evidence",
            }
        ],
        "dependencies": [["Ar@ground", "state"]],
    }
    judgment[field] = changes[field]
    with pytest.raises(ValueError, match="helper view hashes|outcome label"):
        export.validate(document)


def test_dependencies_and_user_input_names_are_validated_without_reassessment() -> None:
    document = saved()
    judgment = document["reactions"][0]["assessments"]["state"]
    judgment["dependencies"] = [["unrecorded@ground", "state"]]
    rehash(document)
    with pytest.raises(ValueError, match="dependency is absent"):
        export.validate(document)
    judgment["dependencies"] = []
    judgment["requirements"] = [
        {
            "responsibility": "user_inputs",
            "target": "Ar@ground",
            "quantity": "unaccepted_input",
            "reason": "not a case input",
        }
    ]
    rehash(document)
    with pytest.raises(ValueError, match="not an accepted input"):
        export.validate(document)


def test_shared_prerequisite_is_one_work_item_with_each_saved_dependent() -> None:
    document = saved()
    for candidate in (*document["states"], *document["reactions"]):
        for judgment in candidate["assessments"].values():
            judgment.update(verdict="pass", requirements=[], dependencies=[])
    state = next(item for item in document["states"] if item["id"] == "Ar@ground")
    state["assessments"]["state"].update(
        verdict="unknown",
        requirements=[
            {
                "responsibility": "source_information",
                "target": state["id"],
                "quantity": "state_existence_support",
                "reason": "a reviewed state assertion is needed",
            }
        ],
    )
    for reaction in document["reactions"][:2]:
        reaction["assessments"]["state"].update(
            verdict="unknown",
            dependencies=[[state["id"], "state"]],
        )
    work = needs.build(document, detail=True)
    task = next(
        item for item in work["work_details"] if item["quantity"] == "state_existence_support"
    )
    assert len(task["affected"]) == 3
    assert work["summary"]["derived_findings"] == 2
    state_tasks = [
        item for item in work["work_details"] if item["quantity"] == "state_existence_support"
    ]
    assert len(state_tasks) == 1
    before = deepcopy(work)
    document["reactions"].reverse()
    document["states"].reverse()
    assert needs.build(document, detail=True) == before


def test_historical_format_two_keeps_empty_meaning_and_its_exact_hashes(tmp_path: Path) -> None:
    document = saved()
    document["metadata"]["helper_view_format"] = 2
    document["reactions"][0]["kinetic_effects"] = ["momentum_transfer"]
    for item in (*document["states"], *document["reactions"]):
        for judgment in item["assessments"].values():
            judgment["proposition"] = ""
            for field in ("scope", "requirements", "dependencies"):
                judgment.pop(field)
            judgment.pop("label")
            judgment.pop("blocking_causes")
    document["summary"] = export.summary(document["states"], document["reactions"])
    rehash(document)
    expected = export.csv_views(document)
    path = tmp_path / "result.yaml"
    path.write_text(yamlio.dump(document), encoding="utf-8")
    export.rebuild_views(document, tmp_path)
    restored = export.read(path, verify_views=True)
    assert restored == document
    assert export.csv_views(restored) == expected
    assert "dataset_id" not in next(csv.DictReader(StringIO(expected["reactions.csv"])))
    assert all(
        not row["proposition"]
        for item in restored["reactions"]
        for row in item["assessments"].values()
    )
