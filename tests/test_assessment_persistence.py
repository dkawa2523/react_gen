"""Saved meaning, dependencies and concrete work stay consistent across views."""

from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from io import StringIO
from pathlib import Path

import pytest

from reactgen import export, needs, yamlio
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze


def saved() -> dict:
    return export.document(analyze(Case("analysis", ("Ar",)), EvidenceCatalog.load(None)))


def rehash(document: dict) -> None:
    document["helper_views"] = {
        name: hashlib.sha256(content.encode()).hexdigest()
        for name, content in export.csv_views(document).items()
    }


def test_individual_scope_requirements_and_dependencies_roundtrip(tmp_path: Path) -> None:
    document = saved()
    rows = {
        row["id"]: row
        for row in csv.DictReader(StringIO(export.csv_views(document)["reactions.csv"]))
    }
    for reaction in document["reactions"]:
        for name, judgment in reaction["assessments"].items():
            row = rows[reaction["id"]]
            assert row[f"{name}_scope"] == judgment["scope"]
            assert json.loads(row[f"{name}_requirements"]) == judgment["requirements"]
            assert json.loads(row[f"{name}_dependencies"]) == judgment["dependencies"]
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
    with pytest.raises(ValueError, match="helper view hashes"):
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
    for item in (*document["states"], *document["reactions"]):
        for judgment in item["assessments"].values():
            judgment["proposition"] = ""
            for field in ("scope", "requirements", "dependencies"):
                judgment.pop(field)
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
