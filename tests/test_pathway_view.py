"""Target-centred pathway topology and rendering."""

from __future__ import annotations

import csv
import json
import re
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from PIL import Image

from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.export import csv_views, document
from reactgen.pathway import reaction_reachability, select_pathway
from reactgen.pathway_view import pathway_png
from reactgen.pipeline import analyze
from reactgen.views import view


def _state(state_id: str, *, feed: bool = False) -> dict:
    return {
        "id": state_id,
        "composition": {state_id: 1},
        "charge": 0,
        "state": {"kind": "ground", "resolution": "resolved", "label": ""},
        "classes": ["feed"] if feed else [],
        "depth": 99,
        "origin": "mechanical",
    }


def _reaction(
    reaction_id: str,
    reactants: tuple[str, ...],
    products: tuple[str, ...],
    *,
    depth: int,
) -> dict:
    return {
        "id": reaction_id,
        "reactants": [{"species": state_id, "n": 1.0} for state_id in reactants],
        "products": [{"species": state_id, "n": 1.0} for state_id in products],
        "family": "neutral",
        "process": "test",
        "reaction_type": "Test reaction",
        "origin": "mechanical",
        "generation_rule": "test",
        "depth": depth,
        "third_body": None,
        "surface": None,
        "kinetic_effects": [],
        "assessments": {
            layer: {"verdict": "pass", "basis": [], "message": ""}
            for layer in (
                "consistency",
                "state",
                "thermochemistry",
                "reaction_evidence",
                "kinetics",
            )
        },
    }


def test_pathway_uses_all_reactants_and_minimum_steps_not_generation_depth() -> None:
    states = [
        _state("A", feed=True),
        _state("B", feed=True),
        _state("X"),
        _state("Y"),
        _state("Z"),
        _state("Q"),
    ]
    reactions = [
        _reaction("via_1", ("A",), ("X",), depth=0),
        _reaction("via_2", ("X", "B"), ("Y",), depth=0),
        _reaction("direct", ("A",), ("Y",), depth=99),
        _reaction("blocked", ("X", "Z"), ("Q",), depth=0),
        _reaction("identity", ("A",), ("A",), depth=0),
    ]

    reachability = reaction_reachability(states, reactions)

    assert reachability.state_layers["X"] == 1
    assert reachability.state_layers["Y"] == 1
    assert "Q" not in reachability.state_layers
    assert "identity" in reachability.reaction_layers
    path = select_pathway(states, reactions, target="Y", reachability=reachability)
    assert path.reaction_ids == ("direct",)
    assert path.state_ids == ("A", "Y")


def test_pathway_png_records_scope_target_and_exact_path_count() -> None:
    states = [_state("A", feed=True), _state("Y")]
    reactions = [_reaction("direct", ("A",), ("Y",), depth=9)]
    rendered = pathway_png(
        case_name="test",
        view_label="screened",
        states=states,
        state_names={"A": "A", "Y": "Y"},
        reactions=reactions,
    )

    with Image.open(BytesIO(rendered)) as image:
        assert image.info["reactgen.scope"] == "target_centered_canonical_hyperpath"
        assert image.info["reactgen.target"] == "Y"
        assert image.info["reactgen.path_reaction_count"] == "1"


def test_pathway_does_not_assume_electron_supply() -> None:
    states = [_state("A", feed=True), _state("e"), _state("X")]
    reactions = [_reaction("electron_channel", ("A", "e"), ("X", "e"), depth=0)]
    default = reaction_reachability(states, reactions)
    assert default.seeds == ("A",)
    assert "X" not in default.state_layers
    supplied = reaction_reachability(states, reactions, seeds=("A", "e"))
    assert supplied.state_layers["X"] == 1
    with pytest.raises(ValueError, match="unknown pathway seed"):
        reaction_reachability(states, reactions, seeds=("missing",))


def test_views_use_one_saved_result_and_explicit_seed_assumptions(tmp_path: Path) -> None:
    saved = document(analyze(Case("view-test", ("Ar",)), EvidenceCatalog.load_paths(())))
    before = json.dumps(saved, sort_keys=True)
    html_path = view(saved, tmp_path, "network")
    html = html_path.read_text(encoding="utf-8")
    match = re.search(r'<script id="network-data" type="application/json">(.*?)</script>', html)
    assert match is not None
    payload = json.loads(match.group(1))
    assert payload["seed_state_ids"] == ["Ar@ground"]
    assert {reaction["id"] for reaction in payload["reactions"]} == {
        reaction["id"] for reaction in saved["reactions"]
    }
    assert all(item["reaction_ids"] is None for item in payload["views"])
    assert "screening" not in html.lower()
    assert "reactions — complete" not in html
    assert "electron not supplied" in payload["pathway_seed_note"]
    tables = csv_views(saved)
    state_rows = list(csv.DictReader(StringIO(tables["states.csv"])))
    reaction_rows = list(csv.DictReader(StringIO(tables["reactions.csv"])))
    assert {row["id"]: row["state"] for row in state_rows} == {
        state["id"]: state["name"] for state in payload["states"]
    }
    assert {row["id"]: row["equation"] for row in reaction_rows} == {
        reaction["id"]: reaction["equation"] for reaction in payload["reactions"]
    }
    assert all("@" not in row["equation"] for row in reaction_rows)
    assert all("@" in reaction["equation"] for reaction in saved["reactions"])
    assert list(state_rows[0])[-1] == list(reaction_rows[0])[-1] == "id"
    assert {row["id"]: row["state_verdict"] for row in state_rows} == {
        state["id"]: state["assessments"]["state"]["verdict"] for state in saved["states"]
    }
    empty_tables = csv_views({"states": [], "reactions": []})
    for filename in tables:
        assert (
            csv.DictReader(StringIO(empty_tables[filename])).fieldnames
            == csv.DictReader(StringIO(tables[filename])).fieldnames
        )
    assert json.dumps(saved, sort_keys=True) == before

    path = view(saved, tmp_path, "pathway", target="Ar+@ground")
    with Image.open(path) as image:
        assert image.info["reactgen.seed_states"] == "Ar@ground"
        assert image.info["reactgen.path_reaction_count"] == "0"
        assert "M and wall" in image.info["reactgen.topology_assumptions"]
    explicit = view(saved, tmp_path, "pathway", seeds=("e", "Ar@ground"), target="Ar+@ground")
    with Image.open(explicit) as image:
        assert image.info["reactgen.path_reaction_count"] == "1"
        assert image.info["reactgen.target"] == "Ar+@ground"

    matrix = view(saved, tmp_path, "matrix")
    with Image.open(matrix) as image:
        assert image.info["reactgen.reaction_count"] == str(len(saved["reactions"]))
        assert image.info["reactgen.scope"] == "all_candidates_no_sampling"


def test_view_options_must_reference_existing_states_and_affect_the_view(tmp_path: Path) -> None:
    saved = document(analyze(Case("view-test", ("Ar",)), EvidenceCatalog.load_paths(())))
    with pytest.raises(ValueError, match="unknown pathway seed"):
        view(saved, tmp_path, "pathway", seeds=("missing",))
    with pytest.raises(ValueError, match="unknown pathway target"):
        view(saved, tmp_path, "pathway", target="missing")
    with pytest.raises(ValueError, match="does not use seed or target"):
        view(saved, tmp_path, "matrix", seeds=("e",))
