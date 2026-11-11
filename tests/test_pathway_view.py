"""Target-centred pathway topology and rendering."""

from __future__ import annotations

import csv
import json
import re
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from PIL import Image

from reactgen.case import Case, Conditions, Limits, RequestedReaction
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.export import csv_views, document, validate
from reactgen.model import ReactionCandidate, Term
from reactgen.pathway import (
    LATER_PRODUCER_CONTEXT,
    MINIMUM_DEPTH_ALTERNATIVE,
    analyze_pathways,
    checked_pathway_query,
    producer_pathway,
    reaction_reachability,
    saved_pathway,
    saved_reachability,
    validate_saved_pathway_graph,
)
from reactgen.pathway_view import _pathway_layout, pathway_png
from reactgen.pipeline import analyze
from reactgen.records import Property, ReactionRecord, StateRecord
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
    path = saved_pathway(reactions, analyze_pathways(states, reactions), target="Y")
    assert path.reaction_ids == ("direct",)
    assert path.state_ids == ("A", "Y")


@pytest.mark.parametrize("scale", [1.0, 1e-20, 1e-200])
def test_positive_production_is_reachable_independently_of_equation_scale(scale):
    states = [_state("A", feed=True), _state("B")]
    reaction = _reaction("production", ("A",), ("B",), depth=0)
    for side in ("reactants", "products"):
        reaction[side][0]["n"] = scale
    reachability = reaction_reachability(states, [reaction])
    assert reachability.state_layers == {"A": 0, "B": 1}
    assert saved_pathway(
        [reaction], analyze_pathways(states, [reaction]), target="B"
    ).reaction_ids == ("production",)


def test_pathway_png_records_scope_target_and_exact_path_count() -> None:
    states = [_state("A", feed=True), _state("Y")]
    reactions = [_reaction("direct", ("A",), ("Y",), depth=9)]
    rendered = pathway_png(
        case_name="test",
        view_label="screened",
        states=states,
        state_names={"A": "A", "Y": "Y"},
        reactions=reactions,
        pathways=analyze_pathways(states, reactions),
    )

    with Image.open(BytesIO(rendered)) as image:
        assert image.info["reactgen.scope"] == "target_centered_canonical_hyperpath"
        assert image.info["reactgen.target"] == "Y"
        assert image.info["reactgen.requested_target"] == "Y"
        assert image.info["reactgen.path_reaction_count"] == "1"
        query = json.loads(image.info["reactgen.pathway_query"])
        assert query["target"] == "Y"
        assert query["seeds"] == ["A"]
        assert query["effective_seeds"] == ["A"]
        assert query["reaction_ids"] == ["direct"]
        assert query["mode"] == "conditioned"
        assert "direct" in query["unresolved"]


def test_pathway_diagram_shows_complete_terms_without_inventing_support() -> None:
    states = [
        _state(species, feed=species in {"CF4", "O2", "e"})
        for species in (
            "CF4",
            "O2",
            "O",
            "e",
            "CF2+",
            "F",
            "CF2O+",
            "CF2O^2+",
        )
    ]
    ionize = _reaction("ionize", ("CF4", "e"), ("CF2+", "F", "F", "e"), depth=8)
    ionize["products"][-1]["n"] = 2.0
    dissociate = _reaction("dissociate", ("O2", "e"), ("O", "O", "e"), depth=9)
    associate = _reaction("associate", ("CF2+", "O"), ("CF2O+",), depth=1)
    associate["third_body"] = "M"
    reionize = _reaction("reionize", ("CF2O+", "e"), ("CF2O^2+", "e"), depth=2)
    reionize["products"][-1]["n"] = 2.0
    reactions = [ionize, dissociate, associate, reionize]
    analysis = analyze_pathways(states, reactions)
    pathway = saved_pathway(reactions, analysis, target="CF2O^2+")
    nodes, edges = _pathway_layout(pathway, reactions, saved_reachability(analysis))

    arcs = {(edge.source, edge.target): edge.count for edge in edges}
    first, second = ("reaction", "ionize"), ("reaction", "associate")
    parallel, later = ("reaction", "dissociate"), ("reaction", "reionize")
    incoming_electrons = {
        edge.target: (edge.source, edge.count)
        for edge in edges
        if nodes[edge.source].subject == "e"
    }
    outgoing_electrons = {
        edge.source: (edge.target, edge.count)
        for edge in edges
        if nodes[edge.target].subject == "e"
    }
    supplied, returned = incoming_electrons[first][0], outgoing_electrons[first][0]
    later_supply, later_output = incoming_electrons[later][0], outgoing_electrons[later][0]
    assert incoming_electrons == {
        first: (supplied, 1),
        parallel: (supplied, 1),
        later: (later_supply, 1),
    }
    assert outgoing_electrons == {
        first: (returned, 2),
        parallel: (returned, 1),
        later: (later_output, 2),
    }
    assert len({supplied, returned, later_supply, later_output}) == 4
    assert nodes[("state", "CF2O+")].level < nodes[later_supply].level
    intermediate = ("state", "CF2+")
    coproduct = ("output", "ionize", "F")
    assert arcs[first, coproduct] == 2
    assert not {edge.source for edge in edges} & {returned, later_output, coproduct}
    assert arcs[first, intermediate] == arcs[intermediate, second] == 1
    assert arcs[parallel, ("state", "O")] == 2
    assert arcs[second, ("state", "CF2O+")] == arcs[("state", "CF2O+"), later] == 1
    assert {
        (nodes[edge.source].subject, nodes[edge.target].subject): edge.count
        for edge in edges
        if "M" in {nodes[edge.source].subject, nodes[edge.target].subject}
    } == {("M", "associate"): 1, ("associate", "M"): 1}
    assert all(nodes[edge.source].level < nodes[edge.target].level for edge in edges)


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

    # A saved electron producer creates a real intermediate. An unchanged
    # electron at the consumer's exit is still a separate terminal occurrence.
    states.append(_state("A+"))
    reactions.append(_reaction("produce_e", ("A",), ("A+", "e"), depth=0))
    analysis = analyze_pathways(states, reactions)
    pathway = saved_pathway(reactions, analysis, target="X")
    nodes, edges = _pathway_layout(pathway, reactions, saved_reachability(analysis))
    assert pathway.supported_by["e"] == "produce_e"
    assert {
        (edge.source, edge.target) for edge in edges if ("state", "e") in {edge.source, edge.target}
    } == {
        (("reaction", "produce_e"), ("state", "e")),
        (("state", "e"), ("reaction", "electron_channel")),
    }
    terminal_electron = [
        edge
        for edge in edges
        if edge.source == ("reaction", "electron_channel") and nodes[edge.target].subject == "e"
    ]
    assert len(terminal_electron) == 1
    assert nodes[terminal_electron[0].target].role == "product"
    assert terminal_electron[0].count == 1


def test_pathway_applies_only_named_rejections_before_minimum_depth() -> None:
    states = [_state("A", feed=True), _state("B"), _state("C")]
    direct = _reaction("direct", ("A",), ("C",), depth=0)
    first = _reaction("first", ("A",), ("B",), depth=0)
    second = _reaction("second", ("B",), ("C",), depth=0)
    direct["assessments"]["energy"] = {
        "verdict": "fail",
        "proposition": "collision_energy_necessary_condition",
        "scope": "the saved state and collision-energy model",
    }
    # Unrelated verdicts and undecided checks do not reject a candidate edge.
    first["assessments"]["thermochemistry"]["verdict"] = "fail"
    first["assessments"]["consistency"].update(
        verdict="unknown", proposition="equation_consistency"
    )
    second["assessments"]["kinetics"]["verdict"] = "fail"
    second["assessments"]["energy"] = {
        "verdict": "unknown",
        "proposition": "collision_energy_necessary_condition",
    }
    reactions = [second, direct, first]
    analysis = analyze_pathways(states, reactions)
    raw = saved_pathway(reactions, analysis, target="C", mode="candidate")
    conditioned = saved_pathway(reactions, analysis, target="C")
    assert raw.reaction_ids == ("direct",)
    assert raw.related_reactions == {"second": LATER_PRODUCER_CONTEXT}
    assert conditioned.reaction_ids == ("first", "second")
    assert analysis["conditioned"]["state_layers"]["C"] == 2
    assert analysis["conditioned"]["excluded"]["direct"] == [
        {"assessment": "energy", "proposition": "collision_energy_necessary_condition"}
    ]
    assert "second" in analysis["conditioned"]["unresolved"]
    assert {"assessment": "consistency", "proposition": "equation_consistency"} in analysis[
        "conditioned"
    ]["unresolved"]["first"]
    second["assessments"]["energy"]["verdict"] = "not_applicable"
    outside_pair = analyze_pathways(states, reactions)
    assert saved_pathway(reactions, outside_pair, target="C").reaction_ids == (
        "first",
        "second",
    )
    assert {
        "assessment": "energy",
        "proposition": "collision_energy_necessary_condition",
        "condition": "energy_condition_not_applied",
    } in outside_pair["conditioned"]["unresolved"]["second"]

    first["assessments"]["consistency"]["verdict"] = "fail"
    current = analyze_pathways(states, reactions)
    historical = analyze_pathways(states, reactions, format_version=7)
    assert "first" in current["candidate"]["reaction_layers"]
    assert "C" not in current["conditioned"]["state_layers"]
    assert current["conditioned"]["excluded"]["first"] == [
        {"assessment": "consistency", "proposition": "equation_consistency"}
    ]
    assert historical["conditioned"]["state_layers"]["C"] == 2
    validate_saved_pathway_graph(states, reactions, historical, format_version=7)
    with pytest.raises(ValueError, match="edge set and supply: conditioned"):
        validate_saved_pathway_graph(states, reactions, historical)


def test_minimum_producer_alternative_is_distinct_from_target_feedback() -> None:
    states = [_state("A", feed=True), _state("B", feed=True), _state("X"), _state("Y"), _state("T")]
    reactions = [
        _reaction("direct", ("A",), ("T",), depth=0),
        _reaction("equal", ("B",), ("T",), depth=0),
        _reaction("ambiguous_input", ("A",), ("Y",), depth=0),
        _reaction("independent_input", ("B",), ("Y",), depth=0),
        _reaction("independent_producer", ("Y",), ("T",), depth=0),
        _reaction("feedback_out", ("T",), ("X",), depth=0),
        _reaction("feedback_in", ("X",), ("T",), depth=0),
        _reaction("autocatalytic", ("A", "T"), ("T", "T"), depth=0),
    ]
    for reaction in reactions:
        if reaction["id"].startswith("independent_"):
            reaction["assessments"].update(
                conservation={"verdict": "pass", "proposition": "element_charge_conservation"},
                consistency={"verdict": "pass", "proposition": "equation_consistency"},
                energy={"verdict": "pass", "proposition": "collision_energy_necessary_condition"},
            )
    result = analyze_pathways(states, reactions)
    assert result["conditioned"]["reaction_layers"]["feedback_in"] == 3
    path = saved_pathway(reactions, result, target="T")
    assert path.reaction_ids == ("direct",)
    assert path.related_reactions == {
        "equal": MINIMUM_DEPTH_ALTERNATIVE,
        "independent_producer": LATER_PRODUCER_CONTEXT,
        "feedback_in": LATER_PRODUCER_CONTEXT,
        "autocatalytic": LATER_PRODUCER_CONTEXT,
        "feedback_out": "target consumer / return",
    }
    choice = producer_pathway(
        states, reactions, result, target="T", via="independent_producer", mode="conditioned"
    )
    assert choice.pathway.reaction_ids == ("independent_input", "independent_producer")
    assert choice.reachability.state_layers == {"B": 0, "Y": 1, "T": 2}
    assert choice.equation_and_energy_checks_pass
    with_target_supply = analyze_pathways(states, reactions, seeds=("A", "B", "T"))
    independent = producer_pathway(
        states,
        reactions,
        with_target_supply,
        target="T",
        via="independent_producer",
        mode="conditioned",
    )
    assert "T" not in independent.reachability.seeds
    assert independent.pathway.reaction_ids == choice.pathway.reaction_ids
    with pytest.raises(ValueError, match="withheld upstream, unreachable reactants: X"):
        producer_pathway(
            states, reactions, result, target="T", via="feedback_in", mode="conditioned"
        )
    with pytest.raises(ValueError, match="withheld upstream, unreachable reactants: T"):
        producer_pathway(
            states, reactions, result, target="T", via="autocatalytic", mode="conditioned"
        )
    upstream = next(reaction for reaction in reactions if reaction["id"] == "independent_input")
    upstream["assessments"]["energy"]["verdict"] = "unknown"
    fallback = producer_pathway(
        states,
        reactions,
        analyze_pathways(states, reactions),
        target="T",
        via="independent_producer",
        mode="conditioned",
    )
    assert fallback.pathway.reaction_ids == ("ambiguous_input", "independent_producer")
    assert not fallback.equation_and_energy_checks_pass

    refuted = _state("R")
    refuted["assessments"] = {
        "state": {"verdict": "fail", "proposition": "state_existence_support"}
    }
    states.append(refuted)
    ambiguous = next(reaction for reaction in reactions if reaction["id"] == "ambiguous_input")
    ambiguous["products"].append({"species": "R", "n": 1.0})
    ambiguous["assessments"].update(
        conservation={"verdict": "pass", "proposition": "element_charge_conservation"},
        consistency={"verdict": "pass", "proposition": "equation_consistency"},
        energy={"verdict": "pass", "proposition": "collision_energy_necessary_condition"},
    )
    for verdict in ("pass", "unknown"):
        upstream["assessments"]["energy"]["verdict"] = verdict
        result = analyze_pathways(states, reactions)
        assert saved_pathway(reactions, result, target="Y").reaction_ids == ("independent_input",)
        choice = producer_pathway(
            states, reactions, result, target="T", via="independent_producer", mode="conditioned"
        )
        assert choice.pathway.reaction_ids == ("independent_input", "independent_producer")
        assert choice.equation_and_energy_checks_pass is (verdict == "pass")


def test_png_surfaces_coproduct_state_claim_separately_from_edge_checks() -> None:
    source, target, coproduct = (_state("A", feed=True), _state("T"), _state("Y"))
    coproduct["state"].update(kind="composition", resolution="lumped")
    coproduct["assessments"] = {
        "state": {"verdict": "fail", "proposition": "state_existence_support"},
        "electron_binding": {"verdict": "unknown", "proposition": "ground_anion_electron_binding"},
    }
    states = [source, target, coproduct]
    reaction = _reaction("direct", ("A",), ("T", "Y"), depth=0)
    for name, proposition in (
        ("conservation", "element_charge_conservation"),
        ("energy", "collision_energy_necessary_condition"),
    ):
        reaction["assessments"][name] = {"verdict": "pass", "proposition": proposition}
    reactions = [reaction]
    result = analyze_pathways(states, reactions)
    assert saved_pathway(reactions, result, target="T").state_ids == ("A", "T")
    rendered = pathway_png(
        case_name="test",
        view_label="conditioned",
        states=states,
        state_names={state["id"]: state["id"] for state in states},
        reactions=reactions,
        pathways=result,
        target="T",
    )
    with Image.open(BytesIO(rendered)) as image:
        query = json.loads(image.info["reactgen.pathway_query"])
    assert not query["unresolved"]
    assert query["unconfirmed_states"] == {"Y": ["composition_hypothesis_not_identified_state"]}
    assert query["state_claims"] == {
        "fail": [{"state": "Y", "assessment": "state", "proposition": "state_existence_support"}],
        "unknown": [
            {
                "state": "Y",
                "assessment": "electron_binding",
                "proposition": "ground_anion_electron_binding",
            }
        ],
    }


def test_png_retains_separate_reasons_for_unreachable_target() -> None:
    states = [_state("A", feed=True), _state("B"), _state("T")]
    excluded = _reaction("threshold", ("A",), ("T",), depth=1)
    excluded["assessments"]["energy"] = {
        "verdict": "fail",
        "proposition": "collision_energy_necessary_condition",
    }
    missing = _reaction("requires_b", ("B",), ("T",), depth=1)
    reactions = [excluded, missing]
    rendered = pathway_png(
        case_name="test",
        view_label="conditioned",
        states=states,
        state_names={state["id"]: state["id"] for state in states},
        reactions=reactions,
        pathways=analyze_pathways(states, reactions),
        target="T",
    )
    with Image.open(BytesIO(rendered)) as image:
        assert image.info["reactgen.target"] == ""
        query = json.loads(image.info["reactgen.pathway_query"])
    assert query["blocked_direct_producers"] == {
        "threshold": {
            "excluded": [
                {
                    "assessment": "energy",
                    "proposition": "collision_energy_necessary_condition",
                    "verdict": "fail",
                }
            ]
        },
        "requires_b": {"unreachable_reactants": ["B"]},
    }


def test_conservation_rejection_and_unidentified_junction_are_separate() -> None:
    start = _state("A", feed=True)
    intermediate = _state("unspecified")
    intermediate["composition"] = {"C": 2, "H": 6, "O": 1}
    intermediate["state"] = {"kind": "composition", "resolution": "lumped", "label": ""}
    states = [start, intermediate, _state("C"), _state("bad")]
    first = _reaction("first", ("A",), ("unspecified",), depth=0)
    second = _reaction("second", ("unspecified",), ("C",), depth=0)
    invalid = _reaction("invalid", ("A",), ("bad",), depth=0)
    invalid["assessments"]["conservation"] = {
        "verdict": "fail",
        "proposition": "element_charge_conservation",
    }
    analysis = analyze_pathways(states, [invalid, first, second])
    assert "bad" not in analysis["candidate"]["state_layers"]
    assert "C" in analysis["conditioned"]["state_layers"]
    assert analysis["unconfirmed_states"]["unspecified"] == [
        "composition_hypothesis_not_identified_state",
        "molecular_structure_unidentified",
    ]


@pytest.mark.parametrize("unverified_structure", [False, True])
def test_conditioned_representative_prefers_supported_chain_at_equal_depth(
    unverified_structure: bool,
) -> None:
    states = [_state("A", feed=True), _state("B"), _state("C"), _state("D")]
    if unverified_structure:
        states[2]["structure"] = "opaque:unchecked"
    reactions = [
        _reaction("a_first", ("A",), ("B",), depth=1),
        _reaction("a_last", ("B",), ("D",), depth=2),
        _reaction("b_first", ("A",), ("C",), depth=1),
        _reaction("b_last", ("C",), ("D",), depth=2),
    ]
    for reaction in reactions:
        reaction["assessments"].update(
            conservation={"verdict": "pass", "proposition": "element_charge_conservation"},
            consistency={"verdict": "pass", "proposition": "equation_consistency"},
            energy={"verdict": "pass", "proposition": "collision_energy_necessary_condition"},
        )
    reactions[0]["assessments"]["energy"]["verdict"] = "unknown"
    result = analyze_pathways(states, reactions)
    assert result["candidate"]["primary_producer"]["D"] == "a_last"
    assert result["conditioned"]["primary_producer"]["D"] == "b_last"
    assert result["conditioned"]["producer_ids"]["D"] == ["a_last", "b_last"]
    assert saved_pathway(reactions, result, target="D").reaction_ids == (
        "b_first",
        "b_last",
    )


def test_checked_query_finds_longer_support_than_an_unchecked_shortcut() -> None:
    unresolved = _state("L")
    unresolved["state"].update(kind="electronic", resolution="lumped")
    states = [_state("A", feed=True), _state("B"), _state("C"), unresolved]
    reactions = [
        _reaction("shortcut", ("A",), ("C",), depth=1),
        _reaction("lumped_coproduct", ("A",), ("C", "L"), depth=1),
        _reaction("step_one", ("A",), ("B",), depth=1),
        _reaction("step_two", ("B",), ("C",), depth=2),
    ]
    for reaction in reactions:
        reaction["assessments"].update(
            conservation={"verdict": "pass", "proposition": "element_charge_conservation"},
            consistency={"verdict": "pass", "proposition": "equation_consistency"},
            energy={"verdict": "pass", "proposition": "collision_energy_necessary_condition"},
        )
    reactions[0]["assessments"]["energy"]["verdict"] = "unknown"
    saved = analyze_pathways(states, reactions)
    queried = checked_pathway_query(states, reactions, saved)
    assert "checked" not in saved
    assert queried["conditioned"]["state_layers"]["C"] == 1
    assert queried["checked"]["state_layers"]["C"] == 2
    assert queried["checked"]["excluded"]["lumped_coproduct"] == [
        {"condition": "unconfirmed_participant_states", "states": ["L"]}
    ]
    path = saved_pathway(reactions, queried, target="C", mode="checked")
    assert path.reaction_ids == ("step_one", "step_two")


def test_checked_supply_requires_evidence_for_an_opaque_structure() -> None:
    collider = candidate_state({"C": 1, "F": 4}, 0, structure="local:unknown")
    case = Case("opaque", ("Ar",), supplies=(collider.id,), limits=Limits(max_depth=1))
    proof = StateRecord(
        "reviewed exact identity",
        collider,
        existence="confirmed",
        existence_source="fixture",
        tier="reviewed",
        review_scope=("state_existence",),
    )
    for records in ((), (proof,)):
        saved = document(analyze(case, EvidenceCatalog(state_records=records)))
        validate(saved)
        pathways = saved["pathways"]
        checked = checked_pathway_query(saved["states"], saved["reactions"], pathways)["checked"]
        assert (collider.id in checked["state_layers"]) == bool(records)
        assert pathways["unconfirmed_states"].get(collider.id) == (
            None if records else ["structure_unverified"]
        )
        if not records:
            old = analyze_pathways(saved["states"], saved["reactions"], format_version=8)
            validate_saved_pathway_graph(saved["states"], saved["reactions"], old, format_version=8)


@pytest.mark.parametrize(
    "refutation", [None, "state_existence_support", "ground_anion_electron_binding"]
)
def test_checked_query_uses_saved_claims_for_an_unchanged_collider(
    tmp_path: Path, refutation: str | None
) -> None:
    # Synthetic records test claim scope. D0 applies to the net endpoints,
    # whereas a physical path also requires the unchanged incident ion.
    collider = candidate_state({"Ar": 1}, -1)
    parent, fragment = candidate_state({"F": 2}, 0), candidate_state({"F": 1}, 0)
    split = ReactionCandidate(
        "split",
        (Term(parent.id),),
        (Term(fragment.id, 2),),
        "neutral",
        "dissociation",
        "test",
        "test",
        0,
    )
    d0 = ReactionRecord(
        "synthetic D0",
        split.equation_key,
        split.family,
        split.process,
        (parent, fragment),
        channel_scope="energy_relation",
        energy_properties={
            "delta_e_eV": Property(2, "eV", tier="reviewed", definition="products_minus_reactants")
        },
    )
    records = []
    if refutation is not None:
        records.append(
            StateRecord(
                "synthetic existence assertion",
                collider,
                existence="unbound" if refutation == "state_existence_support" else "confirmed",
                existence_source="fixture",
                tier="reviewed",
                review_scope=("state_existence",),
            )
        )
    if refutation == "ground_anion_electron_binding":
        records.append(
            StateRecord(
                "synthetic independent binding claim",
                candidate_state({"Ar": 1}, 0),
                properties={
                    "electron_affinity_eV": Property(-1, "eV", tier="reviewed", definition="atomic")
                },
            )
        )
    case = Case(
        "unchanged collider",
        ("F2",),
        supplies=(collider.id,),
        conditions=Conditions(collision_energy_eV=3, collision_energy_frame="com"),
        limits=Limits(max_depth=1),
    )
    saved = document(
        analyze(case, EvidenceCatalog(state_records=tuple(records), reaction_records=(d0,)))
    )
    validate(saved)
    reaction = next(
        row
        for row in saved["reactions"]
        if row["equation"] == f"{collider.id} + {parent.id} -> {collider.id} + 2 {fragment.id}"
    )
    reaction_id = reaction["id"]
    assert reaction["assessments"]["conservation"]["verdict"] == "pass"
    assert reaction["assessments"]["energy"]["verdict"] == "pass"
    for mode in ("candidate", "conditioned"):
        assert reaction_id in saved["pathways"][mode]["producer_ids"][fragment.id]
    checked = checked_pathway_query(saved["states"], saved["reactions"], saved["pathways"])[
        "checked"
    ]
    claims = next(state["assessments"] for state in saved["states"] if state["id"] == collider.id)
    name = "electron_binding" if refutation == "ground_anion_electron_binding" else "state"
    claim = claims[name]
    ref = {"state": collider.id, "assessment": name, "proposition": claim["proposition"]}
    assert "checked" not in saved["pathways"]
    assert fragment.id in checked["state_layers"]  # The unaffected F2 collider branch remains.
    if refutation is None:
        assert claim["verdict"] == "unknown"
        assert reaction_id in checked["producer_ids"][fragment.id]
        assert ref in checked["unresolved"][reaction_id]
        assert checked["state_layers"][collider.id] == 0
    else:
        assert claim["proposition"] == refutation
        assert claim["verdict"] == "fail"
        assert reaction_id not in checked["producer_ids"][fragment.id]
        assert checked["excluded"][reaction_id] == [ref]
        assert collider.id not in checked["state_layers"]
        assert checked["excluded_seeds"][collider.id] == [ref]

        html = view(saved, tmp_path, "network", checked=True, target=collider.id).read_text(
            encoding="utf-8"
        )
        match = re.search(r'<script id="network-data" type="application/json">(.*?)</script>', html)
        assert match is not None
        payload = json.loads(match.group(1))
        assert payload["pathways"]["checked"] == checked
        assert payload["pathways"]["seeds"] == [collider.id, parent.id]
        with Image.open(
            view(saved, tmp_path, "pathway", checked=True, target=collider.id)
        ) as image:
            query = json.loads(image.info["reactgen.pathway_query"])
            assert query["mode"] == "checked"
            assert query["target"] == collider.id
            assert query["excluded_seeds"] == {collider.id: [ref]}
            assert query["effective_seeds"] == [parent.id]
            assert image.info["reactgen.target"] == ""
            assert image.info["reactgen.seed_states"] == parent.id


@pytest.mark.parametrize("corruption", ["wrong_producer", "seedless_layer", "missing_reactant"])
def test_saved_pathway_index_must_match_its_edges_and_supply(corruption: str) -> None:
    saved = document(
        analyze(Case("index", ("Ar",), limits=Limits(max_depth=1)), EvidenceCatalog.load_paths(()))
    )
    mode = saved["pathways"]["conditioned"]
    seeds = set(saved["pathways"]["seeds"])
    target = next(state for state in mode["primary_producer"] if state not in seeds)
    if corruption == "wrong_producer":
        wrong = next(
            reaction["id"]
            for reaction in saved["reactions"]
            if all(term["species"] != target for term in reaction["products"])
        )
        mode["producer_ids"][target] = [wrong]
        mode["primary_producer"][target] = wrong
    elif corruption == "seedless_layer":
        mode["state_layers"][target] = 0
    else:
        required = next(
            term["species"]
            for reaction in saved["reactions"]
            if reaction["id"] in mode["reaction_layers"]
            for term in reaction["reactants"]
            if term["species"] not in seeds and term["species"] != mode["default_target"]
        )
        mode["state_layers"].pop(required)
    with pytest.raises(ValueError, match="saved pathway index"):
        validate(saved)


def test_saved_pathway_default_can_be_any_reachable_produced_target() -> None:
    saved = document(
        analyze(Case("index", ("Ar",), limits=Limits(max_depth=1)), EvidenceCatalog.load_paths(()))
    )
    mode = saved["pathways"]["conditioned"]
    mode["default_target"] = next(
        state
        for state in mode["producer_ids"]
        if mode["state_layers"][state] > 0 and state != mode["default_target"]
    )
    for notes in mode["unresolved"].values():
        notes.reverse()
    validate(saved)
    assert saved_pathway(saved["reactions"], saved["pathways"]).target == mode["default_target"]


def test_views_use_one_saved_result_and_explicit_seed_assumptions(tmp_path: Path) -> None:
    saved = document(
        analyze(
            Case("view-test", ("Ar",), limits=Limits(max_depth=1)), EvidenceCatalog.load_paths(())
        )
    )
    before = json.dumps(saved, sort_keys=True)
    html_path = view(saved, tmp_path, "network")
    html = html_path.read_text(encoding="utf-8")
    match = re.search(r'<script id="network-data" type="application/json">(.*?)</script>', html)
    assert match is not None
    payload = json.loads(match.group(1))
    status = "Partial candidate exploration. Recorded stop reason: max_depth=1."
    assert payload["exploration_status"] == status
    assert payload["pathways"]["seeds"] == ["Ar@ground"]
    assert {reaction["id"] for reaction in payload["reactions"]} == {
        reaction["id"] for reaction in saved["reactions"]
    }
    assert "screening" not in html.lower()
    assert "reactions — complete" not in html
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
    state_judgments = csv.DictReader(StringIO(tables["judgments/state-support.csv"]))
    assert {row["id"]: row["verdict"] for row in state_judgments} == {
        state["id"]: state["assessments"]["state"]["verdict"] for state in saved["states"]
    }
    empty_tables = csv_views(
        {"metadata": saved["metadata"], "states": [], "reactions": [], "input": {}}
    )
    for filename in ("states.csv", "reactions.csv"):
        assert (
            csv.DictReader(StringIO(empty_tables[filename])).fieldnames
            == csv.DictReader(StringIO(tables[filename])).fieldnames
        )
    assert json.dumps(saved, sort_keys=True) == before

    path = view(saved, tmp_path, "pathway", target="Ar+@ground")
    with Image.open(path) as image:
        assert image.info["reactgen.seed_states"] == "Ar@ground"
        assert image.info["reactgen.exploration_status"] == status
        query = json.loads(image.info["reactgen.pathway_query"])
        # Heavy-particle ionization may itself produce electrons. That is a
        # conditional candidate, not an implicit electron supply or known rate.
        selected = {
            reaction["id"]: reaction
            for reaction in saved["reactions"]
            if reaction["id"] in query["reaction_ids"]
        }
        layers = saved["pathways"]["conditioned"]["reaction_layers"]
        assert all(
            "e" not in {term["species"] for term in reaction["reactants"]}
            for reaction_id, reaction in selected.items()
            if layers[reaction_id] == 1
        )
        assert query["unresolved"]
        assumptions = image.info["reactgen.topology_assumptions"]
        assert "AND reachability" in assumptions
        assert "do not track individual particles" in assumptions
    explicit = view(saved, tmp_path, "pathway", seeds=("e", "Ar@ground"), target="Ar+@ground")
    with Image.open(explicit) as image:
        assert image.info["reactgen.path_reaction_count"] == "1"
        assert image.info["reactgen.target"] == "Ar+@ground"

    matrix = view(saved, tmp_path, "matrix")
    with Image.open(matrix) as image:
        assert image.info["reactgen.reaction_count"] == str(len(saved["reactions"]))
        assert image.info["reactgen.scope"] == "all_candidates_no_sampling"
        assert image.info["reactgen.exploration_status"] == status


def test_pathway_views_surface_all_limits_and_unexpanded_requested_branch(tmp_path: Path) -> None:
    ionization = RequestedReaction("e + Ar+ -> Ar^2+ + 2 e", "ionization")
    saved = document(
        analyze(
            Case(
                "bounded",
                ("Ar",),
                supplies=("e",),
                reactions=(ionization,),
                limits=Limits(max_depth=1, max_atoms=1, max_reactions=2),
            ),
            EvidenceCatalog.load_paths((Path(__file__).parents[1] / "registry",)),
        )
    )
    generation = saved["metadata"]["generation"]
    assert generation["stop_reason"] == "max_reactions=2"
    requested = ionization.candidate.id
    skipped = {"depth": 2, "reason": "max_reactions=2"}
    target = "Ar^2+@ground"
    image_path = view(saved, tmp_path, "pathway", target=target)
    with Image.open(image_path) as image:
        assert "max_reactions=2, max_depth=1" in image.info["reactgen.exploration_status"]
        query = json.loads(image.info["reactgen.pathway_query"])
        assert requested in query["reaction_ids"]
        assert query["skipped_requested_expansions"] == {requested: skipped}
    html = view(saved, tmp_path, "network", target=target).read_text(encoding="utf-8")
    match = re.search(r'<script id="network-data" type="application/json">(.*?)</script>', html)
    assert match is not None
    assert json.loads(match.group(1))["skipped_requested_expansions"] == {requested: skipped}


def test_view_options_must_reference_existing_states_and_affect_the_view(tmp_path: Path) -> None:
    saved = document(
        analyze(
            Case("view-test", ("Ar",), limits=Limits(max_depth=1)), EvidenceCatalog.load_paths(())
        )
    )
    with pytest.raises(ValueError, match="unknown pathway seed"):
        view(saved, tmp_path, "pathway", seeds=("missing",))
    with pytest.raises(ValueError, match="absent from the saved candidates.*max_depth=1"):
        view(saved, tmp_path, "pathway", target="missing")
    with pytest.raises(ValueError, match="does not use --seed, --target"):
        view(saved, tmp_path, "matrix", seeds=("e",))
    with pytest.raises(ValueError, match="--via requires a saved state ID specified with --target"):
        view(saved, tmp_path, "pathway", via="missing")
    with pytest.raises(ValueError, match="unknown saved producer reaction"):
        view(saved, tmp_path, "network", target="Ar@ground", via="missing")
