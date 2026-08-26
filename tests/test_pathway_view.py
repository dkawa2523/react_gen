"""Target-centred pathway topology and rendering."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from reactgen.pathway import reaction_reachability, select_pathway
from reactgen.pathway_view import pathway_png


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
