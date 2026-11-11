"""Exact spectroscopic endpoints in ordinary, bounded case analysis."""

from pathlib import Path

import pytest

from reactgen import export
from reactgen.case import Case, CollisionPair, Conditions, Limits, RequestedReaction
from reactgen.chemistry import parse_equation, parse_state_id
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.structure import StructureUnavailable, structure_key


@pytest.fixture(scope="module")
def catalog() -> EvidenceCatalog:
    return EvidenceCatalog.load(Path(__file__).resolve().parents[1] / "registry")


@pytest.mark.parametrize(
    ("gas", "target", "energy", "levels", "manifold"),
    [
        ("Ar", "Ar", 11.6, {"1s5": (11.54836, "pass"), "1s4": (11.62359, "fail")}, "4s"),
        ("Ar", "Ar+", 0.18, {"2p1/2": (0.17749368, "pass")}, None),
        ("O", "O", 0.022, {"3p1": (0.01962236, "pass"), "3p0": (0.02814156, "fail")}, "3p"),
    ],
)
def test_resolved_registry_levels_qualify_separate_endpoint_gaps(
    catalog, gas, target, energy, levels, manifold
):
    # NIST SRD 108 Ar I/Ar II/O I level tables give ground-relative wavenumbers.
    # The chosen COM energies distinguish neighboring thresholds in the same term.
    case = Case(
        name=f"{target} levels",
        gases=(gas,),
        supplies=("e",) if target == gas else ("e", target),
        conditions=Conditions(
            collision_energy_eV=energy,
            collision_energy_frame="com",
            projectile_state="e",
            target_state=target,
        ),
        limits=Limits(max_depth=1, max_atoms=1),
    )
    result = analyze(case, catalog)
    by_label = {
        result.candidates.states[term.species].state.label.casefold(): (reaction, term.species)
        for reaction in result.candidates.reactions.values()
        if reaction.family == "electron" and reaction.process == "excitation"
        if {term.species for term in reaction.reactants} == {"e", f"{target}@ground"}
        for term in reaction.products
        if term.species != "e"
    }
    for label, (gap_eV, verdict) in levels.items():
        reaction, state_id = by_label[label]
        claims = result.evaluation.reaction_assessments[reaction.id]
        gap = result.evaluation.thermochemical_calculations[reaction.id]["level_gap_1_eV"]
        assert result.evaluation.state_assessments[state_id]["state"].verdict == "pass"
        assert gap.value == pytest.approx(gap_eV, rel=1e-6)
        assert claims["energy"].verdict == verdict
        assert claims["reaction_evidence"].verdict == "unknown"
    if manifold:
        reaction, _ = by_label[manifold]
        assert result.evaluation.reaction_assessments[reaction.id]["energy"].verdict == "unknown"


@pytest.mark.parametrize(
    ("gas", "smiles", "isotope", "label", "wavenumber"),
    [
        ("NF3", "N(F)(F)F", "[15N](F)(F)F", "v2=1", 647.1340617),
        ("SiH4", "[SiH4]", "[29SiH4]", "v4=1", 913.46833),
    ],
)
def test_registry_vibrational_levels_follow_only_the_identified_graph(
    catalog, tmp_path, gas, smiles, isotope, label, wavenumber
):
    probe = parse_state_id(f"{gas}@ground;structure=smiles:{smiles}")
    assert probe is not None
    try:
        structure_key(probe)
    except StructureUnavailable as error:
        pytest.skip(str(error))
    limits = Limits(max_depth=1, max_atoms=5)
    conditions = Conditions(
        collision_pairs=(
            CollisionPair("e", gas, 0.12, "com"),
            CollisionPair("e", f"{gas}@{label}", 0.01, "com"),
        )
    )
    excitation = RequestedReaction(f"e + {gas} -> e + {gas}@{label}", "excitation")
    arguments = {"conditions": conditions, "supplies": ("e",), "limits": limits}
    case = Case("structured vibration", (gas,), structures={gas: smiles}, **arguments)
    generated = analyze(case, catalog)
    target = next(
        reaction
        for reaction in generated.candidates.reactions.values()
        if reaction.process == "excitation"
        and any(
            generated.candidates.states[term.species].state.label == label
            for term in reaction.products
        )
        and all(
            term.species == "e" or generated.candidates.states[term.species].structure
            for term in reaction.reactants
        )
    )
    excited_id = next(term.species for term in target.products if term.species != "e")
    ground_id = next(term.species for term in target.reactants if term.species != "e")
    excited = generated.candidates.states[excited_id]
    assert excited.structure == generated.candidates.states[ground_id].structure
    assert generated.evaluation.state_evidence[excited_id].match == "exact"
    assert generated.evaluation.state_assessments[excited_id]["state"].verdict == "pass"
    assert generated.evaluation.reaction_assessments[target.id]["energy"].verdict == "pass"
    gap = generated.evaluation.thermochemical_calculations[target.id]["level_gap_1_eV"]
    assert gap.value == pytest.approx(wavenumber * 1.239841984e-4)
    difference = generated.evaluation.thermochemical_calculations[target.id][
        "state_energy_difference_eV"
    ]
    assert any(term.get("related_state") == ground_id for term in difference.inputs)
    assert any(
        state.id == ground_id for state in catalog.declared_states(structural_context=(excited,))
    )

    requested = analyze(
        Case(case.name, (gas,), structures={gas: smiles}, reactions=(excitation,), **arguments),
        catalog,
    )
    assert target.id in requested.candidates.reactions
    assert parse_equation(requested.input["reactions"][0]["equation"])[0] == target.equation_key
    assert requested.evaluation.reaction_assessments[target.id]["energy"].verdict == "pass"
    assert any(
        pair["target_state"] == excited_id
        for pair in requested.input["conditions"]["collision_pairs"]
    )
    export.write(tmp_path / "result", requested)
    saved = export.read(tmp_path / "result", verify_views=True)
    record = next(state for state in saved["states"] if state["id"] == excited_id)["evidence"][
        "records"
    ][0]
    assert record["properties"]["excitation_energy_eV"]["related_state"] == f"{gas}@ground"

    different = analyze(Case(case.name, (gas,), structures={gas: isotope}, **arguments), catalog)
    assert not any(
        state.state.label == label and state.structure
        for state in different.candidates.states.values()
    )
    different_request = analyze(
        Case(case.name, (gas,), structures={gas: isotope}, reactions=(excitation,), **arguments),
        catalog,
    )
    different_equation = parse_equation(different_request.input["reactions"][0]["equation"])[0]
    assert different_equation[3] == excitation.candidate.equation_key[3]


@pytest.mark.parametrize(
    ("initial", "final", "gap", "verdict"),
    [("1s5", "1s2", 0.27971673, "fail"), ("1s2", "1s5", -0.27971673, "pass")],
)
def test_penning_donor_direction_is_independent_of_collision_energy(
    catalog, initial, final, gap, verdict
):
    # A nominally allowed collision can raise the donor's energy. Penning
    # ionization specifically requires a release of donor internal energy.
    # IUPAC Gold Book 12520, https://doi.org/10.1351/goldbook.12520.
    hypothesis = RequestedReaction(f"Ar@{initial} + O -> Ar@{final} + O+ + e", "penning_ionization")
    result = analyze(
        Case(
            "Penning donor direction",
            ("Ar", "O"),
            supplies=(f"Ar@{initial}",),
            conditions=Conditions(
                collision_energy_eV=20,
                collision_energy_frame="com",
                projectile_state=f"Ar@{initial}",
                target_state="O",
            ),
            limits=Limits(max_depth=1),
            reactions=(hypothesis,),
        ),
        catalog,
    )
    by_process = {
        reaction.process: reaction.id
        for reaction in result.candidates.reactions.values()
        if reaction.equation_key == hypothesis.candidate.equation_key
    }
    claims = result.evaluation.reaction_assessments
    penning, generic = by_process["penning_ionization"], by_process["collision_ionization"]
    assert claims[penning]["consistency"].verdict == verdict
    assert claims[generic]["consistency"].verdict == "pass"
    for reaction in (penning, generic):
        assert claims[reaction]["energy"].verdict == "pass"
        actual = result.evaluation.thermochemical_calculations[reaction]["level_gap_1_eV"]
        assert actual.value == pytest.approx(gap)


def test_atom_pair_internal_change_has_no_net_association_loss(catalog):
    hypothesis = RequestedReaction("2 Ar -> Ar@1s5 + Ar", "net_association_loss")
    case = Case(
        "Ar internal change",
        ("Ar",),
        conditions=Conditions(collision_energy_eV=12, collision_energy_frame="com"),
        limits=Limits(max_depth=1, max_atoms=2),
        reactions=(hypothesis,),
    )
    result = analyze(case, catalog)
    matching = {
        reaction.process: reaction
        for reaction in result.candidates.reactions.values()
        if reaction.equation_key == hypothesis.candidate.equation_key
    }
    assert matching["net_association_loss"].origin == "requested"
    assert matching["level_transfer"].origin == "mechanical"
    claims = result.evaluation.reaction_assessments
    assert claims[matching["net_association_loss"].id]["consistency"].verdict == "fail"
    assert claims[matching["level_transfer"].id]["consistency"].verdict == "pass"


def test_group_exchange_generation_excludes_internal_state_changes(catalog):
    equation = "N2 + NF -> N2 + NF@a1d"
    exchange = RequestedReaction(equation, "net_group_exchange")
    case = Case("NF internal change", ("N2", "NF"), limits=Limits(max_depth=1, max_atoms=4))
    result = analyze(case, catalog)
    matching = {
        reaction.process
        for reaction in result.candidates.reactions.values()
        if reaction.equation_key == exchange.candidate.equation_key
    }
    assert "level_transfer" in matching
    assert "net_group_exchange" not in matching
    requested = analyze(
        Case(case.name, case.gases, limits=case.limits, reactions=(exchange,)), catalog
    )
    claims = requested.evaluation.reaction_assessments[exchange.candidate.id]
    assert claims["consistency"].verdict == "fail"


def test_electron_direction_uses_signed_gap_between_excited_levels(catalog):
    # NIST WebBook C13967061 lists the origins of the a¹Δ and b¹Σ⁺ NF bands.
    equation = "e + NF@b1s%2B -> e + NF@a1d"
    upward = RequestedReaction(equation, "excitation")
    downward = RequestedReaction(equation, "deexcitation")
    case = Case(
        "signed NF level gap",
        ("He",),
        supplies=("e", "NF@b1s%2B"),
        conditions=Conditions(collision_energy_eV=0.1, collision_energy_frame="com"),
        limits=Limits(max_depth=1, max_atoms=2),
        reactions=(upward, downward),
    )
    result = analyze(case, catalog)
    for requested, verdict in ((upward, "fail"), (downward, "pass")):
        identifier = requested.candidate.id
        assert result.evaluation.reaction_assessments[identifier]["consistency"].verdict == verdict
        gap = result.evaluation.thermochemical_calculations[identifier]["level_gap_1_eV"]
        assert gap.value == pytest.approx(-0.926167)
