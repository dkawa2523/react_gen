"""Inventory invariants, explicit supplies and finite shared generation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from reactgen.assessment import assess_consistency
from reactgen.balance import conservation
from reactgen.case import Case, Conditions, Limits, RequestedReaction
from reactgen.chemistry import candidate_state, composition_partitions, parse_state_id
from reactgen.evidence import EvidenceCatalog, snapshot_state
from reactgen.export import document, read, write
from reactgen.generate import candidates
from reactgen.model import ReactionCandidate, Term
from reactgen.pathway import checked_pathway_query
from reactgen.pipeline import analyze
from reactgen.records import Property, ReactionRecord, StateRecord
from reactgen.structure import (
    StructureUnavailable,
    bind_structure,
    fragment_edits,
    pair_edits,
    structure_key,
    validate_graph_transformation,
)

SMALL = Limits(max_depth=2, max_species=90, max_reactions=600, max_candidate_trials=3000)


@pytest.mark.parametrize("gases", [("Ar",), ("Ar", "O2"), ("Ar", "CF4"), ("BCl3", "NH3")])
def test_generated_equations_conserve_inventory_and_have_no_partial_registration(gases):
    generated = candidates(gases, SMALL)
    for reaction in generated.reactions.values():
        balance = conservation(reaction.reactants, reaction.products, generated.states)
        assert not balance.missing
        assert balance.elements_conserved
        assert balance.charge_conserved
        assert assess_consistency(reaction, generated).verdict != "fail", reaction


@pytest.mark.parametrize("written", ["argon", "Ar+", "O2(v=1)", "O0", "not-a-formula", 3])
def test_gas_shorthand_is_neutral_ground_formula(written):
    with pytest.raises(ValueError, match="neutral ground-state"):
        candidates((written,), SMALL)


def test_explicit_supplies_share_the_input_and_save_boundaries():
    case = Case.from_document(
        {
            "gases": ["NH3"],
            "supplies": ["e", "H3+"],
            "conditions": {"collision_energy_eV": 2, "collision_energy_frame": "com"},
        }
    )
    assert case.supplies == ("H3+@ground", "e")
    assert case.conditions.collision_energy_frame == "com"
    assert Case.from_document(case.document()) == case
    generated = candidates(case.gases, SMALL, supplies=case.supplies)
    assert {state.id for state in generated.states.values() if "feed" in state.classes} == {
        "e",
        "H3+@ground",
        "H3N@ground",
    }
    ordinary = candidates(("Ar",), SMALL)
    assert "feed" not in ordinary.states["e"].classes


@pytest.mark.parametrize(
    "bad",
    [{"target_at_rest": 1}, {"collision_energy_frame": "mean"}, {"projectile_state": "nothing"}],
)
def test_non_numeric_collision_conditions_have_their_own_domain(bad):
    with pytest.raises(ValueError, match="boolean|com or lab|particle state"):
        Conditions(**bad)


def test_default_atom_envelope_holds_initial_binary_growth_and_is_explicit():
    case = Case("bound", ("SiH4",))
    assert case.limits.max_atoms == 10
    generated = candidates(("Ar",))
    assert generated.complete
    assert generated.unexpanded == []
    assert generated.limits["max_atoms"] == 2
    assert any(state.composition == {"Ar": 2} for state in generated.states.values())
    with pytest.raises(ValueError, match="max_atoms"):
        candidates(("SiH4",), replace(SMALL, max_atoms=4))


def test_formula_partition_does_not_require_an_invented_bond_graph():
    parts = list(composition_partitions({"C": 1, "H": 4}, 3))
    assert parts
    assert len({tuple(tuple(sorted(p.items())) for p in row) for row in parts}) == len(parts)
    for row in parts:
        assert all(row)
        assert {element: sum(p.get(element, 0) for p in row) for element in ("C", "H")} == {
            "C": 1,
            "H": 4,
        }
    generated = candidates(("C2H6O",), replace(SMALL, max_depth=1))
    hypotheses = [state for state in generated.states.values() if state.state.kind == "composition"]
    assert hypotheses
    assert all(
        state.state.resolution == "lumped" and state.structure is None for state in hypotheses
    )


def test_electron_partition_retains_balanced_channels_with_distinct_electron_counts():
    generated = candidates(
        ("CH4",), replace(SMALL, max_depth=1, max_reactions=2000, max_species=300)
    )
    exits = set()
    three_fragments = False
    for reaction in generated.reactions.values():
        transform = reaction.transformation
        if transform.get("kind") != "electron_partition":
            continue
        outgoing = sum(term.n for term in reaction.products if term.species == "e")
        assert transform["outgoing_electrons"] == outgoing
        assert conservation(
            reaction.reactants, reaction.products, generated.states
        ).charge_conserved
        exits.add(outgoing)
        three_fragments |= sum(term.n for term in reaction.products if term.species != "e") == 3
    assert exits == {0, 1, 2}
    assert three_fragments


def _interpretations(transformation):
    return transformation.get("alternatives", [transformation])


def test_dissociation_can_retain_or_change_the_exact_collider_state():
    excited = candidate_state({"Ar": 1}, 0, "metastable", structure="smiles:[36Ar]")
    ground = candidate_state({"Ar": 1}, 0, structure=excited.structure)
    generated = candidates(("H2",), replace(SMALL, max_depth=1), supplies=(excited.id,))
    exits = {
        (reaction.process, mapped["collider_product"])
        for reaction in generated.reactions.values()
        for mapped in _interpretations(reaction.transformation)
        if mapped.get("kind") == "collision_partition"
        and mapped["parent"] == "H2@ground"
        and mapped["collider"] == excited.id
        and mapped["fragments"] == ["H@ground", "H@ground"]
        and "unresolved_nuclides" not in mapped
    }
    assert exits == {
        ("collision_induced_dissociation", excited.id),
        ("dissociation_with_level_transfer", ground.id),
    }


def test_collision_dissociation_uses_exact_isotope_endpoints_and_parent_graph(monkeypatch):
    pytest.importorskip("rdkit.Chem")
    parent = bind_structure(parse_state_id("H2"), "[2H][2H]")
    fragment = bind_structure(parse_state_id("H"), "[2H]")
    d0 = ReactionCandidate(
        "d0",
        (Term(parent.id),),
        (Term(fragment.id, 2),),
        "neutral",
        "dissociation",
        "test",
        "test",
        0,
    )
    # Synthetic value tests exact participant identity and spectator cancellation.
    record = ReactionRecord(
        d0.id,
        d0.equation_key,
        d0.family,
        d0.process,
        (parent, fragment),
        channel_scope="energy_relation",
        energy_properties={
            "delta_e_eV": Property(
                4.55, "eV", tier="reviewed", definition="products_minus_reactants"
            )
        },
    )
    case = Case(
        "isotope dissociation",
        ("Ar", "H2"),
        Conditions(collision_energy_eV=8.0, collision_energy_frame="com"),
        limits=replace(SMALL, max_depth=1),
        structures={"H2": "[2H][2H]"},
    )
    result = analyze(case, EvidenceCatalog(reaction_records=(record,)))
    saved = document(result)
    exact = next(
        channel
        for channel in saved["reactions"]
        if channel["process"] == "collision_induced_dissociation"
        and {term["species"]: term["n"] for term in channel["products"]}
        == {"Ar@ground": 1, fragment.id: 2}
    )
    assessments = exact["assessments"]
    assert {assessments[key]["verdict"] for key in ("conservation", "consistency", "energy")} == {
        "pass"
    }
    assert exact["thermochemical_calculations"]["state_energy_difference_eV"][
        "value"
    ] == pytest.approx(4.55)
    graph = next(
        mapped
        for mapped in _interpretations(exact["transformation"])
        if mapped["kind"] == "graph_edit"
    )
    assert {item["state"] for item in graph["reactant_graphs"]} == {parent.id}
    assert graph["collider"] == graph["collider_product"] == "Ar@ground"
    reaction = result.candidates.reactions[exact["id"]]
    incorrect = {**graph, "edits": [{"action": "break", "atoms": [1, 3], "bond": "SINGLE"}]}
    assert (
        assess_consistency(replace(reaction, transformation=incorrect), result.candidates).verdict
        == "fail"
    )
    monkeypatch.setattr("reactgen.assessment.validate_graph_transformation", lambda *a, **k: None)
    graph_only = replace(reaction, transformation=graph)
    pending = assess_consistency(graph_only, result.candidates)
    assert pending.verdict == "unknown"
    assert "fragmentation mapping" in pending.message
    assert assess_consistency(reaction, result.candidates).verdict == "pass"
    coarse = next(
        channel
        for channel in saved["reactions"]
        if channel["process"] == "collision_induced_dissociation"
        and {term["species"]: term["n"] for term in channel["products"]}
        == {"Ar@ground": 1, "H@ground": 2}
    )
    assert coarse["assessments"]["conservation"]["verdict"] == "unknown"
    assert coarse["assessments"]["energy"]["verdict"] == "unknown"


def test_heavy_detachment_emits_one_electron_and_is_not_ionization():
    generated = candidates(("Ar", "O2"), replace(SMALL, max_depth=1), supplies=("O2-",))
    exits = {
        (reaction.process, tuple(reaction.products))
        for reaction in generated.reactions.values()
        if {term.species for term in reaction.reactants} == {"Ar@ground", "O2-@ground"}
        and any(term.species == "e" for term in reaction.products)
        and any(
            mapped.get("parent") == "O2-@ground"
            for mapped in _interpretations(reaction.transformation)
        )
    }
    assert exits
    assert {process for process, _ in exits} == {
        "collisional_detachment",
        "dissociative_detachment",
    }
    assert all(("e", 1) in products for _, products in exits)
    assert any(
        process == "dissociative_detachment" and ("O@ground", 2) in products
        for process, products in exits
    )


def test_excited_ion_can_change_its_own_level_while_the_target_ionizes():
    generated = candidates(("Ne",), replace(SMALL, max_depth=1), supplies=("Ar+@metastable",))
    exits = {
        (mapped.get("collider_product", mapped.get("collider")), tuple(reaction.products))
        for reaction in generated.reactions.values()
        for mapped in _interpretations(reaction.transformation)
        if reaction.family == "ion"
        and reaction.process == "collision_ionization"
        and mapped.get("parent") == "Ne@ground"
        and mapped.get("collider") == "Ar+@metastable"
    }
    assert {
        ("Ar+@ground", (("e", 1), ("Ar+@ground", 1), ("Ne+@ground", 1))),
        ("Ar+@metastable", (("e", 1), ("Ar+@metastable", 1), ("Ne+@ground", 1))),
    } <= exits


def test_charged_group_transfer_discovers_proton_transfer_with_known_product_alternatives():
    identified = candidate_state({"N": 1, "H": 4}, 1, structure="source:ammonium")
    hydrogen = candidate_state({"H": 2}, 0)
    generated = candidates(
        ("NH3",),
        replace(SMALL, max_depth=1, max_reactions=1000),
        supplies=("H3+",),
        known_states=(identified, hydrogen),
    )
    matching = []
    for reaction in generated.reactions.values():
        for transform in _interpretations(reaction.transformation):
            if (
                transform.get("kind") == "group_transfer"
                and transform.get("donor") == "H3+@ground"
                and transform.get("group") == {"H": 1}
                and transform.get("group_charge") == 1
            ):
                matching.append(reaction)
    assert matching
    assert any(identified.id in {term.species for term in r.products} for r in matching)
    unspecified = candidate_state({"N": 1, "H": 4}, 1, "composition", resolution="lumped")
    assert any(unspecified.id in {term.species for term in r.products} for r in matching)
    assert generated.states[identified.id].key != generated.states[unspecified.id].key


def test_closed_shell_inputs_keep_association_and_group_hypotheses():
    generated = candidates(("BCl3", "NH3"), replace(SMALL, max_depth=1))
    pair = {"BCl3@ground", "H3N@ground"}
    reactions = [
        r for r in generated.reactions.values() if {t.species for t in r.reactants} == pair
    ]
    assert {"net_association", "net_group_transfer"} <= {r.process for r in reactions}
    assert all(r.transformation for r in reactions)
    assert any(
        sum(generated.states[t.species].composition.values()) == 8
        for r in reactions
        for t in r.products
    )


def test_budgets_count_trials_and_stop_without_orphan_products():
    generated = candidates(("F2",), replace(SMALL, max_candidate_trials=8))
    assert generated.trials == 8
    assert not generated.complete
    assert "max_candidate_trials" in generated.stop_reason
    assert generated.unexpanded
    assert all(
        set(task["participants"]) <= generated.states.keys() for task in generated.unexpanded
    )
    tiny = candidates(("Ar",), Limits(max_species=2))
    assert set(tiny.states) == {"Ar@ground", "e"}
    assert not tiny.complete
    with pytest.raises(ValueError, match="cannot retain"):
        candidates(("Ar", "F2"), Limits(max_species=2))


def test_species_budget_leaves_existing_state_reactions_available():
    gases = ("Ar", "Ne")
    supplies = ("e", "Ar+", "Ne+")
    limits = Limits(max_depth=1, max_species=5, expand_unresolved_states=False)
    declared = RequestedReaction("e + Ne+ + Ar -> Ne + Ar", "recombination")
    case = Case(
        "fixed state inventory", gases, limits=limits, supplies=supplies, reactions=(declared,)
    )
    analysis = analyze(case, EvidenceCatalog())
    generated = analysis.candidates
    unrestricted = candidates(gases, replace(limits, max_species=300), supplies=supplies)
    closed_inventory = {
        row.id
        for row in unrestricted.reactions.values()
        if all(term.species in generated.states for term in (*row.reactants, *row.products))
    }
    ionization = RequestedReaction("e + Ar -> 2 e + Ar+", "ionization")
    assert ionization.candidate.id in closed_inventory
    assert set(generated.reactions) == closed_inventory | {declared.candidate.id}
    assert generated.reactions[declared.candidate.id].depth == 1
    assert len(generated.states) == limits.max_species
    saved = document(analysis)
    generation = saved["metadata"]["generation"]
    assert not generation["complete"]
    assert generation["stop_reason"] == "max_species=5"
    assert len(generation["unexpanded"]) == 1
    assert generation["unexpanded"][0]["operation"] == "mechanical_state_registration"


def test_resolved_exploration_keeps_hypotheses_and_allows_declared_exits():
    ion = candidate_state({"H": 2}, 1, "composition", resolution="lumped")
    exit_channel = RequestedReaction(f"{ion.id} + e -> H+ + H + e", "dissociation")
    case = Case(
        "resolved exploration",
        ("H2",),
        supplies=("e",),
        limits=Limits(max_depth=2, expand_unresolved_states=False),
        reactions=(exit_channel,),
    )
    result = analyze(case, EvidenceCatalog())
    generated = result.candidates
    assert ion.id in generated.states
    assert any(
        row.origin == "mechanical" and ion.id in {term.species for term in row.products}
        for row in generated.reactions.values()
    )
    assert all(
        generated.states[term.species].state.resolution == "resolved"
        for row in generated.reactions.values()
        if row.origin == "mechanical"
        for term in row.reactants
    )
    nominated = generated.reactions[exit_channel.candidate.id]
    assert nominated.origin == "requested"
    assert nominated.depth == 2
    assert any(
        row.depth == 2 and row.origin == "mechanical" and Term("H@ground") in row.reactants
        for row in generated.reactions.values()
    )
    saved = document(result)
    assert saved["input"]["limits"] == saved["metadata"]["generation"]["limits"]
    assert saved["input"]["limits"]["expand_unresolved_states"] is False

    supplied = candidates(case.gases, replace(case.limits, max_depth=1), supplies=("e", ion.id))
    assert any(
        row.origin == "mechanical" and Term(ion.id) in row.reactants
        for row in supplied.reactions.values()
    )


@pytest.mark.parametrize(
    "declaration",
    [
        {"supplies": ("H@ground;structure=smiles:[O]",)},
        {"supplies": ("H",), "structures": {"H": "[O]"}},
    ],
)
def test_contradictory_input_structure_is_rejected_before_search(declaration):
    pytest.importorskip("rdkit.Chem")
    case = Case("structure", ("Ar",), limits=replace(SMALL, max_candidate_trials=1), **declaration)
    with pytest.raises(ValueError, match="SMILES composition or charge contradicts"):
        analyze(case, EvidenceCatalog())


def test_expansion_does_not_reassign_a_declared_collision_partner():
    pytest.importorskip("rdkit.Chem")
    fluorine = bind_structure(parse_state_id("F"), "[F]")
    case = Case(
        "collision pair",
        ("F",),
        supplies=("e",),
        structures={"F": "[F]"},
        conditions=Conditions(
            collision_energy_eV=2,
            collision_energy_frame="com",
            projectile_state="e",
            target_state="F",
        ),
        limits=Limits(max_atoms=1, max_depth=2, max_candidate_trials=2),
    )
    small, larger = (
        document(
            analyze(
                replace(case, limits=replace(case.limits, max_candidate_trials=limit)),
                EvidenceCatalog(),
            )
        )
        for limit in (2, 30)
    )
    assert "F@ground" not in {state["id"] for state in small["states"]}
    assert "F@ground" in {state["id"] for state in larger["states"]}
    for saved in (small, larger):
        assert saved["input"]["conditions"]["target_state"] == fluorine.id
        collision = next(
            reaction
            for reaction in saved["reactions"]
            if reaction["process"] == "elastic"
            and {term["species"] for term in reaction["reactants"]} == {"e", fluorine.id}
        )
        assert collision["assessments"]["energy"]["verdict"] == "pass"


def test_explicit_collision_smiles_binds_to_the_same_input_graph():
    pytest.importorskip("rdkit.Chem")
    fluorine = bind_structure(parse_state_id("F2"), "[F][F]")
    case = Case(
        "collision pair",
        ("Ar",),
        supplies=("e", "F2"),
        structures={"F2": "[F][F]"},
        conditions=Conditions(
            collision_energy_eV=2,
            collision_energy_frame="com",
            projectile_state="e",
            target_state="F2@ground;structure=smiles:[F][F]",
        ),
        limits=Limits(max_atoms=2, max_depth=1, max_candidate_trials=250),
    )
    unrelated = StateRecord(
        "rejected structure",
        candidate_state({"F": 1}, 0, structure="smiles:[Cl]"),
        status="rejected",
    )
    saved = document(analyze(case, EvidenceCatalog(state_records=(unrelated,))))
    assert saved["input"]["conditions"]["target_state"] == fluorine.id
    collision = next(
        reaction
        for reaction in saved["reactions"]
        if reaction["process"] == "elastic"
        and {term["species"] for term in reaction["reactants"]} == {"e", fluorine.id}
    )
    assert collision["assessments"]["energy"]["verdict"] == "pass"


def test_input_order_and_duplicates_do_not_change_the_candidate_set():
    first = candidates(("Ar", "F2"), SMALL)
    second = candidates(("F2", "Ar", "Ar"), SMALL)
    assert first.states == second.states
    assert first.reactions == second.reactions


@pytest.mark.parametrize(
    ("charge", "kind"),
    [(-3, "ground"), (-1, "ground"), (0, "composition"), (1, "resolved"), (3, "ground")],
)
def test_canonical_identity_roundtrip_keeps_resolution_charge_and_structure(charge, kind):
    state = candidate_state(
        {"C": 2, "H": 6, "O": 1},
        charge,
        kind,
        resolution="lumped" if kind == "composition" else "resolved",
        structure="source:isomer;tag=2",
    )
    restored = parse_state_id(state.id)
    assert restored is not None
    assert restored.key == state.key


def test_missing_structure_dependency_retains_inventory_work_and_exact_cause(monkeypatch):
    def unavailable():
        raise StructureUnavailable("RDKit dependency cannot load") from ImportError("blocked DLL")

    monkeypatch.setattr("reactgen.structure._chem", unavailable)
    generated = candidates(("Ar",), Limits(max_atoms=1), structures={"Ar@ground": "[Ar]"})
    assert generated.generation_gaps
    assert any(r.process == "ionization" for r in generated.reactions.values())
    assert any(
        state.structure == "smiles:[Ar]" and "feed" in state.classes
        for state in generated.states.values()
    )
    assert not any(
        state.id == "Ar@ground" and "feed" in state.classes for state in generated.states.values()
    )
    assert not generated.complete
    assert generated.completion["mechanical"] is False
    assert any("RDKit" in gap["reason"] for gap in generated.generation_gaps)
    # The available inventory work reached closure; unavailable graph tasks remain in gaps.
    assert generated.unexpanded == []


def test_unverified_smiles_is_saved_but_cannot_supply_a_checked_pathway(monkeypatch):
    def unavailable():
        raise StructureUnavailable("RDKit dependency cannot load")

    monkeypatch.setattr("reactgen.structure._chem", unavailable)
    reaction = RequestedReaction("e + F@ground;structure=smiles:[F] -> e + F", "elastic")
    explicit_state = next(state.id for state in reaction.states if state.structure)
    case = Case(
        "declared structures",
        ("CF4",),
        supplies=("e",),
        structures={"CF4": "O"},
        reactions=(reaction,),
        limits=Limits(max_depth=1, max_reactions=3),
    )
    saved = document(analyze(case, EvidenceCatalog()))
    feed = next(state for state in saved["states"] if state.get("structure") == "smiles:O")
    assert feed["assessments"]["consistency"]["verdict"] == "unknown"
    assert feed["id"] in saved["pathways"]["seeds"]
    pathways = checked_pathway_query(saved["states"], saved["reactions"], saved["pathways"])
    checked = pathways["checked"]
    assert feed["id"] in checked["excluded_seeds"]
    assert any(
        gap["operation"] == "graph_input" and gap["target"] == explicit_state
        for gap in saved["metadata"]["generation"]["gaps"]
    )


def test_graph_process_label_must_match_the_declared_bond_change():
    pytest.importorskip("rdkit.Chem")
    donor = bind_structure(parse_state_id("NH3"), "N")
    acceptor = bind_structure(parse_state_id("BCl3"), "ClB(Cl)Cl")
    edit = next(
        edit
        for edit in pair_edits(donor, acceptor, 1)
        if edit is not None and edit.process == "coordinate_addition"
    )
    assert validate_graph_transformation(
        (donor, acceptor), edit.products, edit.transformation, process="coordinate_addition"
    )
    assert (
        validate_graph_transformation(
            (donor, acceptor), edit.products, edit.transformation, process="radical_recombination"
        )
        is False
    )


def test_identified_graph_product_is_a_separate_branch_with_its_own_map_reference():
    identified = candidate_state({"C": 3, "H": 7}, 0, structure="smiles:CC[CH2]")
    other_isomer = candidate_state(identified.composition, 0, structure="smiles:C[CH]C")
    pytest.importorskip("rdkit.Chem")
    generated = candidates(
        ("CH3", "C2H4"),
        replace(SMALL, max_depth=1),
        known_states=(identified, other_isomer),
        structures={"CH3": "[CH3]", "C2H4": "C=C"},
    )
    branches = [
        reaction
        for reaction in generated.reactions.values()
        if reaction.process == "radical_addition"
    ]
    targets = {term.species for reaction in branches for term in reaction.products}
    assert identified.id in targets
    assert other_isomer.id not in targets
    assert any(generated.states[target].state.kind == "composition" for target in targets)
    assert all(assess_consistency(reaction, generated).verdict == "pass" for reaction in branches)


@pytest.mark.parametrize(
    ("left", "left_smiles", "right", "right_smiles", "process"),
    [
        ("F", "[F]", "SiH4", "[SiH4]", "radical_abstraction"),
        ("CH3", "[CH3]", "C2H5", "[CH2]C", "radical_disproportionation"),
        ("SiH2", "[SiH2]", "H2", "[H][H]", "insertion"),
        ("CH3", "[CH3]", "CH3", "[CH3]", "radical_recombination"),
        ("CH3", "[CH3]", "C2H4", "C=C", "radical_addition"),
        ("NH3", "N", "BCl3", "ClB(Cl)Cl", "coordinate_addition"),
        ("H2O", "O", "AlCl3", "Cl[Al](Cl)Cl", "coordinate_addition"),
        ("F", "[F]", "SiH4", "[SiH4]", "substitution"),
        ("F-", "[F-]", "CH3Cl", "CCl", "substitution"),
        ("F", "[F]", "SiH4", "[2H][Si]([2H])([2H])[2H]", "radical_abstraction"),
    ],
)
def test_explicit_graph_recipes_and_replay(left, left_smiles, right, right_smiles, process):
    pytest.importorskip("rdkit.Chem")
    a = bind_structure(parse_state_id(left), left_smiles)
    b = bind_structure(parse_state_id(right), right_smiles)
    edits = [item for item in pair_edits(a, b, 1) if item is not None and item.process == process]
    assert edits
    for edit in edits:
        assert (
            validate_graph_transformation(
                (a, b), edit.products, edit.transformation, process=process
            )
            is True
        )


@pytest.mark.parametrize(
    ("formula", "structure", "product", "max_atoms"),
    [
        ("H2", "[2H][2H]", "[1H][2H]", 2),
        ("SiH4", "[28Si]([2H])([2H])([2H])[2H]", "[1H][28Si]([2H])([2H])[2H]", 5),
    ],
)
def test_labelled_atom_exchange_keeps_maps_and_produces_a_saved_target(
    tmp_path, formula, structure, product, max_atoms
):
    pytest.importorskip("rdkit.Chem")
    case = Case(
        "isotope exchange",
        (formula,),
        Conditions(collision_energy_eV=1.0, collision_energy_frame="com"),
        limits=Limits(max_atoms=max_atoms, max_depth=1),
        supplies=("H",),
        structures={formula: structure, "H": "[1H]"},
    )
    result = analyze(case, EvidenceCatalog())
    saved = write(tmp_path, result)
    assert read(tmp_path, verify_views=True) == saved
    exchange = next(
        reaction for reaction in saved["reactions"] if reaction["process"] == "isotope_exchange"
    )
    by_id = {state["id"]: state for state in saved["states"]}
    products = [by_id[term["species"]] for term in exchange["products"]]
    assert {state["structure"] for state in products} == {f"smiles:{product}", "smiles:[2H]"}
    target = next(state["id"] for state in products if state["structure"] == f"smiles:{product}")
    assert exchange["id"] in saved["pathways"]["conditioned"]["producer_ids"][target]
    assessments = exchange["assessments"]
    assert assessments["conservation"]["verdict"] == "pass"
    assert assessments["consistency"]["verdict"] == "pass"
    assert assessments["energy"]["verdict"] == "unknown"

    reaction = result.candidates.reactions[exchange["id"]]
    assert not any(
        other.equation_key == reaction.equation_key
        and other.process in {"substitution", "radical_abstraction"}
        for other in result.candidates.reactions.values()
    )
    if formula == "SiH4":
        assert any(
            item["process"] == "radical_abstraction"
            and any(
                by_id[term["species"]]["structure"] == "smiles:[1H][2H]"
                for term in item["products"]
            )
            for item in saved["reactions"]
        )
    declared = reaction.transformation["alternatives"][0]
    attacker, centre, leaving = declared["edits"][0]["atoms"]
    wrong_roles = {
        **declared,
        "edits": [{"action": "isotope_exchange", "atoms": [leaving, centre, attacker]}],
    }
    wrong = replace(reaction, transformation=wrong_roles)
    assert assess_consistency(wrong, result.candidates).verdict == "fail"
    unmapped = replace(reaction, transformation={})
    assert assess_consistency(unmapped, result.candidates).verdict == "unknown"


@pytest.mark.parametrize("incoming", ["[2H]", "[H]"])
def test_atom_diatom_exchange_does_not_infer_an_unlabelled_or_unchanged_isotope(incoming):
    pytest.importorskip("rdkit.Chem")
    atom = bind_structure(parse_state_id("H"), incoming)
    molecule = bind_structure(parse_state_id("H2"), "[2H][2H]")
    edits = list(pair_edits(atom, molecule, 1))
    assert all(item is None or item.process != "isotope_exchange" for item in edits)


def test_polyatomic_isotope_exchange_requires_a_connected_neutral_molecule():
    pytest.importorskip("rdkit.Chem")
    atom = bind_structure(parse_state_id("H"), "[1H]")
    disconnected = bind_structure(parse_state_id("HeSiH4"), "[28Si]([2H])([2H])([2H])[2H].[4He]")
    edits = list(pair_edits(atom, disconnected, 1))
    assert all(item is None or item.process != "isotope_exchange" for item in edits)


def test_explicit_fragment_cuts_and_dative_reversal_replay_with_atom_maps():
    pytest.importorskip("rdkit.Chem")
    ethane = bind_structure(parse_state_id("C2H6"), "CC")
    donor = bind_structure(parse_state_id("NH3"), "N")
    acceptor = bind_structure(parse_state_id("BCl3"), "ClB(Cl)Cl")
    adduct = next(
        edit.products[0]
        for edit in pair_edits(donor, acceptor, 1)
        if edit is not None and edit.process == "coordinate_addition"
    )
    literal_dative = bind_structure(candidate_state({"N": 1, "H": 3, "Cu": 1}, 1), "N->[Cu+]")
    for parent in (ethane, adduct, literal_dative):
        edits = [edit for edit in fragment_edits(parent, 1) if edit is not None]
        assert edits
        assert {len(edit.products) for edit in edits} == {2, 3}
        for edit in edits:
            assert sum(state.charge for state in edit.products) == parent.charge
            assert (
                validate_graph_transformation(
                    (parent,), edit.products, edit.transformation, process="dissociation"
                )
                is True
            )
    originals = {structure_key(donor), structure_key(acceptor)}
    reversals = [
        edit
        for edit in fragment_edits(adduct, 1)
        if edit is not None
        and any(change["action"] == "coordinate_break" for change in edit.transformation["edits"])
    ]
    assert reversals
    assert any({structure_key(state) for state in edit.products} == originals for edit in reversals)
    assert all(sum(state.charge for state in edit.products) == adduct.charge for edit in reversals)
    assert any(
        change.get("bond") == "DATIVE"
        for edit in fragment_edits(literal_dative, 1)
        if edit is not None
        for change in edit.transformation["edits"]
    )


def test_external_graph_target_inventory_and_mapped_nuclides_must_agree():
    pytest.importorskip("rdkit.Chem")
    parent = bind_structure(parse_state_id("H2"), "[2H][2H]")
    edit = next(edit for edit in fragment_edits(parent, 1) if edit is not None)
    for species, smiles in (("CH4", "[CH3]"), ("CH3+", "[CH3]")):
        record = snapshot_state(
            {"species": species, "phase": "gas", "structure": "smiles:" + smiles}, {}
        )
        assert record is not None
        with pytest.raises(ValueError, match="SMILES composition or charge contradicts"):
            structure_key(record.candidate)
    assert validate_graph_transformation((parent,), edit.products, edit.transformation) is True
    mapped = edit.transformation["products"]
    wrong = [
        {**part, "mapped_smiles": part["mapped_smiles"].replace("[2H:", "[H:")} for part in mapped
    ]
    assert (
        validate_graph_transformation(
            (parent,), edit.products, {**edit.transformation, "products": wrong}
        )
        is False
    )
    unlabelled = candidate_state({"H": 1}, 0)
    unresolved = {
        **edit.transformation,
        "products": [{**part, "state": unlabelled.id} for part in mapped],
    }
    assert validate_graph_transformation((parent,), (unlabelled, unlabelled), unresolved) is None
