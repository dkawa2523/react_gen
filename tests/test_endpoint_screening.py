"""Small endpoint cycles, distinct from measured channel probabilities.

The synthetic energies below test thermochemical identities, not the numerical
properties of the named species. Definitions/signs follow NIST ion chemistry:
https://webbook.nist.gov/chemistry/ion/ .
"""

import json
import re
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from reactgen.assessment import assess_consistency, evaluate
from reactgen.case import Case, Conditions, Limits, RequestedReaction
from reactgen.chemistry import candidate_state, electron_state
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.export import csv_views, document, read, validate, write
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.presentation import registered_records
from reactgen.records import FormationReference, Property, ReactionRecord, SourceRef, StateRecord
from reactgen.selection import DataSelection, QuantitySelection
from reactgen.views import view


def _reaction(name, left, right, family="electron", process="dissociation", **kwargs):
    return ReactionCandidate(
        name,
        tuple(Term(x) for x in left),
        tuple(Term(x) for x in right),
        family,
        process,
        "test",
        "test",
        0,
        **kwargs,
    )


def _evaluate(reaction, states, records=(), relations=(), energy=3):
    states = {s.id: s for s in states}
    states["e"] = electron_state()
    return evaluate(
        CandidateSet(states, {reaction.id: reaction}),
        EvidenceCatalog(tuple(records), tuple(relations)),
        Conditions(collision_energy_eV=energy, collision_energy_frame="com"),
    )


def _prop(value, **kwargs):
    return Property(value, "eV", tier="reviewed", **kwargs)


def test_catalog_reference_is_available_outside_bounded_candidate_search(tmp_path):
    catalog = EvidenceCatalog.load(Path(__file__).resolve().parents[1] / "registry")
    requested = RequestedReaction("e + Ar@1s5 -> Ar+ + 2 e", "ionization")
    target = requested.candidate.id
    case = Case(
        "Ar I 1s5 ionization",
        ("He",),
        supplies=("e", "Ar@1s5"),
        reactions=(requested,),
        limits=Limits(max_depth=1, max_atoms=1, max_species=3),
    )
    small = analyze(case, catalog)
    large = analyze(replace(case, limits=replace(case.limits, max_species=30)), catalog)
    assert "Ar@ground" not in small.candidates.states
    assert "Ar@ground" in large.candidates.states
    assert "Ar@ground" not in small.metadata["supply_state_ids"]
    difference = "state_energy_difference_eV"
    calculation = small.evaluation.thermochemical_calculations[target][difference]
    assert calculation == large.evaluation.thermochemical_calculations[target][difference]
    # Registry Ar I ground IE minus the NIST ASD 1s5 excitation energy.
    assert calculation.value == pytest.approx(15.7596119 - 11.548355079770634)

    saved = write(tmp_path, small)
    restored = read(tmp_path / "result.yaml", verify_views=True)
    assert restored == saved
    ground_term = next(term for term in calculation.inputs if term["target"] == "Ar@ground")
    record_id = ground_term["record_id"]
    record = restored["scientific_records"][record_id]
    assert record["calculation_target"] == record["candidate"]["id"] == "Ar@ground"
    assert any(
        item["record_id"] == record_id and item["record_target"] == "Ar@ground"
        for item in registered_records(restored, target, difference)["records"]
    )
    listing = registered_records(restored, "Ar@ground", "ionization_energy_eV")
    assert listing["target_scope"] == "calculation_reference"
    assert listing["records"][0]["record_ref"] == ground_term["record_ref"]
    targeted = DataSelection(
        targets={
            "Ar@ground": {
                "ionization_energy_eV": QuantitySelection(record=ground_term["record_ref"])
            }
        }
    )
    reselected = analyze(replace(case, data_selection=targeted), catalog)
    assert reselected.evaluation.thermochemical_calculations[target][difference] == calculation
    write(tmp_path, reselected)
    assert read(tmp_path, verify_views=True)["input"]["data_selection"] == targeted.document()

    excluded = replace(
        targeted,
        targets={"Ar@ground": {"ionization_energy_eV": QuantitySelection(record="absent")}},
    )
    uncomputed = analyze(replace(case, data_selection=excluded), catalog)
    assert (
        uncomputed.evaluation.thermochemical_calculations[target][difference].status
        == "unavailable"
    )
    write(tmp_path, uncomputed)
    saved_exclusion = read(tmp_path, verify_views=True)
    assert registered_records(saved_exclusion, "Ar@ground", "ionization_energy_eV")["records"]
    unrelated = DataSelection(targets={"Ar@ground": {"mass_amu": QuantitySelection()}})
    with pytest.raises(ValueError, match="unsupported quantities for this target: mass_amu"):
        analyze(replace(case, data_selection=unrelated), catalog)
    record["calculation_target"] = "He@ground"
    with pytest.raises(ValueError, match="calculation state record contradicts its target"):
        validate(restored)

    selection = DataSelection({"ionization_energy_eV": QuantitySelection(record="absent")})
    restricted = analyze(replace(case, data_selection=selection), catalog).evaluation
    assert restricted.thermochemical_calculations[target][difference].status == "unavailable"
    assert "Ar@ground" not in restricted.calculation_state_records


def test_saved_calculation_uses_exact_declaration_when_sources_reuse_ids(tmp_path, capsys):
    ground = candidate_state({"Ar": 1}, 0)
    upper = candidate_state(ground.composition, 0, "resolved", label="upper")
    shared_id = "shared-portable-id"
    records = [
        StateRecord(
            upper.id,
            upper,
            properties={"excitation_energy_eV": _prop(1, related_state=ground.id)},
        )
    ]
    for provider, ionization, mass in (("A", 15, 39), ("B", 16, 40)):
        for state, quantity, prop in (
            (ground, "ionization_energy_eV", _prop(ionization, definition="atomic")),
            (upper, "mass_amu", Property(mass, "u", tier="reviewed")),
        ):
            source = SourceRef(provider=provider, record_id=quantity)
            records.append(
                StateRecord(
                    state.id,
                    state,
                    record_id=shared_id,
                    properties={quantity: replace(prop, provenance=source)},
                    provenance=source,
                )
            )
    request = RequestedReaction("e + Ar@upper -> Ar+ + 2 e", "ionization")
    case = Case(
        "reused declaration IDs",
        ("He",),
        Conditions(electron_energy_eV=15.5, target_at_rest=True),
        supplies=("e", "Ar@upper"),
        limits=Limits(max_depth=1, max_atoms=1, max_species=3),
        reactions=(request,),
        data_selection=DataSelection(
            {
                "ionization_energy_eV": QuantitySelection(providers=("A", "B")),
                "mass_amu": QuantitySelection(providers=("A", "B")),
            }
        ),
    )
    catalog = EvidenceCatalog(tuple(records))
    analysis = analyze(case, catalog)
    assert ground.id not in analysis.candidates.states
    saved = write(tmp_path, analysis)
    assert read(tmp_path, verify_views=True) == saved
    target = request.candidate.id
    reaction = next(item for item in saved["reactions"] if item["id"] == target)
    calculations = reaction["thermochemical_calculations"]
    difference = calculations["state_energy_difference_eV"]
    assert difference["value"] == 14
    assert {item["value"] for item in difference["alternatives"]} == {15}
    assert (
        len(
            [
                item
                for item in saved["scientific_records"].values()
                if item.get("calculation_target") == ground.id and item["record_id"] == shared_id
            ]
        )
        == 2
    )

    def listed(quantity):
        assert main(["records", str(tmp_path), "--target", target, "--quantity", quantity]) == 0
        return [
            item
            for item in yaml.safe_load(capsys.readouterr().out)["records"]
            if item.get("record_id") == shared_id
        ]

    sources = listed("delta_e_eV")
    assert {
        (item["properties"]["ionization_energy_eV"]["value"], item["energy_uses"][0]["status"])
        for item in sources
    } == {(15, "selected"), (16, "alternative")}
    mass = listed("mass_amu")
    assert len(mass) == 1
    assert mass[0]["properties"]["mass_amu"]["value"] == 39
    assert mass[0]["provenance"]["provider"] == "A"

    alternate = next(item for item in sources if item["provenance"]["provider"] == "B")
    explicit = DataSelection(
        {
            "ionization_energy_eV": QuantitySelection(record=alternate["record_ref"]),
            "mass_amu": QuantitySelection(record=mass[0]["record_ref"]),
        }
    )
    reselected = analyze(
        replace(case, data_selection=explicit), EvidenceCatalog(tuple(reversed(records)))
    )
    assert (
        reselected.evaluation.thermochemical_calculations[target][
            "state_energy_difference_eV"
        ].value
        == 15
    )
    mismatched = deepcopy(saved)
    reaction = next(item for item in mismatched["reactions"] if item["id"] == target)
    inputs = reaction["thermochemical_calculations"]["state_energy_difference_eV"]["inputs"]
    next(term for term in inputs if term.get("record_id") == shared_id)["record_ref"] = alternate[
        "record_ref"
    ]
    with pytest.raises(ValueError, match="absent scientific record, target or quantity"):
        validate(mismatched)

    # A format-8 writer could keep only the last reused ID. Its computed
    # number remains readable, but the surviving 16 eV record cannot back 15 eV.
    legacy = deepcopy(saved)
    legacy["metadata"]["helper_view_format"] = 8
    legacy["scientific_records"] = {
        record["record_id"]: record
        for record in legacy["scientific_records"].values()
        if record["provenance"]["provider"] != "A"
    }
    for row in legacy["reactions"]:
        for result in row["thermochemical_calculations"].values():
            for offer in (result, *result.get("alternatives", ())):
                for term in offer.get("inputs", ()):
                    term.pop("record_ref", None)
    legacy["helper_views"] = {
        name: sha256(content.encode()).hexdigest() for name, content in csv_views(legacy).items()
    }
    validate(legacy)
    old_sources = registered_records(legacy, target, "delta_e_eV")["records"]
    old_shared = [item for item in old_sources if item.get("record_id") == shared_id]
    assert len(old_shared) == 1
    assert old_shared[0]["energy_uses"][0]["status"] == "alternative"


def test_calculation_reference_does_not_borrow_a_different_phase():
    ground = candidate_state({"Ar": 1}, 0)
    excited = candidate_state(ground.composition, 0, "resolved", label="upper")
    ion = candidate_state(ground.composition, 1)
    solid = candidate_state(ground.composition, 0, phase="solid")
    reaction = _reaction("ionize", ["e", excited.id], ["e", "e", ion.id], process="ionization")
    records = (
        StateRecord(
            excited.id,
            excited,
            properties={"excitation_energy_eV": _prop(1, related_state=ground.id)},
        ),
        StateRecord(
            solid.id,
            solid,
            properties={"ionization_energy_eV": _prop(8, definition="atomic")},
        ),
    )
    result = _evaluate(reaction, (excited, ion), records)
    difference = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert difference.status == "unavailable"
    assert not result.calculation_state_records


def test_anion_binding_uses_and_preserves_a_catalog_only_neutral_reference(tmp_path):
    ground = candidate_state({"Ar": 1}, 0)
    # Synthetic reviewed EA tests a binding exclusion, independent of real Ar data.
    accepted = SourceRef(provider="accepted", citation="shared citation")
    excluded = SourceRef(provider="excluded", citation="shared citation")
    affinity = StateRecord(
        ground.id,
        ground,
        properties={"electron_affinity_eV": _prop(-1, definition="atomic", provenance=accepted)},
        record_id="reused-affinity-id",
        provenance=accepted,
    )
    other = replace(
        affinity,
        provenance=excluded,
        properties={"electron_affinity_eV": _prop(1, definition="atomic", provenance=excluded)},
    )
    catalog = EvidenceCatalog((affinity, other))
    case = Case(
        "anion binding reference",
        ("He",),
        supplies=("e", "Ar-"),
        limits=Limits(max_depth=1, max_atoms=1, max_species=3),
        data_selection=DataSelection(
            {"electron_affinity_eV": QuantitySelection(mode="only", providers=("accepted",))}
        ),
    )
    small = analyze(case, catalog)
    large = analyze(replace(case, limits=replace(case.limits, max_species=30)), catalog)
    assert ground.id not in small.candidates.states
    assert ground.id in large.candidates.states
    anion = "Ar-@ground"
    binding = small.evaluation.state_assessments[anion]["electron_binding"]
    assert binding == large.evaluation.state_assessments[anion]["electron_binding"]
    assert binding.verdict == "fail"
    assert small.evaluation.state_assessments[anion]["state"].verdict == "unknown"
    assert "reused-affinity-id" in binding.basis

    saved = write(tmp_path, small)
    assert read(tmp_path / "result.yaml", verify_views=True) == saved
    assert set(saved["scientific_records"]) == {"reused-affinity-id"}
    reference = saved["scientific_records"]["reused-affinity-id"]
    assert reference["calculation_target"] == ground.id
    assert reference["properties"]["electron_affinity_eV"]["value"] == -1
    (displayed,) = registered_records(saved, anion, "electron_affinity_eV")["records"]
    assert displayed["record_ref"] == binding.record_inputs[0].record_ref
    assert displayed["assessment_uses"][0]["target"] == ground.id
    claim = next(state for state in saved["states"] if state["id"] == anion)["assessments"][
        "electron_binding"
    ]
    claim["record_inputs"][0]["record_ref"] = "record-ref:" + "0" * 64
    with pytest.raises(ValueError, match="assessment refers to an absent scientific record"):
        validate(saved)


def test_ionization_requirements_distinguish_missing_adiabatic_energy_and_conflict():
    neutral = candidate_state({"Ar": 1}, 0)
    ion = candidate_state(neutral.composition, 1)
    reaction = _reaction("ionize", ["e", neutral.id], ["e", "e", ion.id], process="ionization")
    records = tuple(
        StateRecord(
            neutral.id,
            neutral,
            properties={"ionization_energy_eV": _prop(value, definition="atomic")},
            record_id=f"IE-{value}",
        )
        for value in (8, 10)
    )
    unreviewed = replace(records[0], properties={"ionization_energy_eV": Property(8, "eV")})
    for data, responsibility in (
        ((), "source_information"),
        ((unreviewed,), "source_review"),
        (records, "source_selection"),
    ):
        result = _evaluate(reaction, (neutral, ion), records=data)
        difference = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
        assert difference.value is None
        (requirement,) = difference.requirements
        assert (requirement.responsibility, requirement.target, requirement.quantity) == (
            responsibility,
            neutral.id,
            "ionization_energy_eV",
        )
        if responsibility != "source_review":
            assert ion.id in requirement.reason
        assert "products-minus-reactants" in requirement.reason


@pytest.mark.parametrize(("energy", "verdict"), [(27.0, "fail"), (28.0, "pass")])
def test_positive_charge_step_uses_only_the_uncancelled_adjacent_ionization_energy(energy, verdict):
    first = candidate_state({"Ar": 1}, 1)
    second = candidate_state(first.composition, 2)
    reaction = _reaction("step", ["e", first.id], ["e", "e", second.id], process="ionization")
    record = StateRecord(
        first.id,
        first,
        properties={"ionization_energy_eV": _prop(27.62967, related_state=second.id)},
    )
    result = _evaluate(reaction, (first, second), records=(record,), energy=energy)
    delta = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value == 27.62967
    (source,) = delta.inputs
    assert (source["target"], source["related_state"], source["coefficient"]) == (
        first.id,
        second.id,
        1,
    )
    assert result.reaction_assessments[reaction.id]["energy"].verdict == verdict

    wrong = replace(
        record,
        properties={"ionization_energy_eV": _prop(15.7596119, related_state=first.id)},
    )
    unsupported = _evaluate(reaction, (first, second), records=(wrong,), energy=energy)
    assert unsupported.reaction_assessments[reaction.id]["energy"].verdict == "unknown"
    missing = unsupported.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    (requirement,) = missing.requirements
    assert (requirement.responsibility, requirement.target, requirement.quantity) == (
        "identity",
        first.id,
        "ionization_energy_eV.relation",
    )

    nonpositive = replace(
        record,
        properties={"ionization_energy_eV": _prop(0, related_state=second.id)},
    )
    invalid = _evaluate(reaction, (first, second), records=(nonpositive,), energy=energy)
    assert invalid.reaction_assessments[reaction.id]["energy"].verdict == "unknown"
    assert any(
        item.responsibility == "source_review" and item.quantity == "ionization_energy_eV.value"
        for item in invalid.reaction_assessments[reaction.id]["thermochemistry"].requirements
    )


def test_ion_charge_exchange_uses_signed_positive_stages_and_cancels_lower_references():
    ar_plus = candidate_state({"Ar": 1}, 1)
    ar_double = candidate_state(ar_plus.composition, 2)
    ne = candidate_state({"Ne": 1}, 0)
    ne_plus = candidate_state(ne.composition, 1)
    reaction = _reaction(
        "exchange", [ar_double.id, ne.id], [ar_plus.id, ne_plus.id], "ion", "charge_exchange"
    )
    records = (
        StateRecord(ar_plus.id, ar_plus, properties={"ionization_energy_eV": _prop(27)}),
        StateRecord(ne.id, ne, properties={"ionization_energy_eV": _prop(20)}),
    )
    result = _evaluate(reaction, (ar_plus, ar_double, ne, ne_plus), records=records, energy=0)
    delta = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value == -7
    assert {item["target"]: item["coefficient"] for item in delta.inputs} == {
        ar_plus.id: -1,
        ne.id: 1,
    }
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "pass"


@pytest.mark.parametrize("explicit_graph", [False, True], ids=["atom", "molecule"])
def test_ground_ionization_order_applies_to_direct_and_derived_endpoint_differences(explicit_graph):
    if explicit_graph:
        pytest.importorskip("rdkit.Chem")
        neutral = candidate_state({"N": 2}, 0, structure="smiles:N#N")
        ion = candidate_state(neutral.composition, 1, structure="smiles:[N+]#N")
    else:
        neutral = candidate_state({"H": 1}, 0)
        ion = candidate_state(neutral.composition, 1)
    reaction = _reaction("ionize", ["e", neutral.id], ["e", "e", ion.id], process="ionization")
    invalid = ReactionRecord(
        "inverted-ionization",
        reaction.equation_key,
        "electron",
        "ionization",
        (neutral, ion),
        channel_scope="energy_relation",
        energy_properties={"delta_e_eV": _prop(-1, definition="products_minus_reactants")},
    )
    reference = FormationReference(0, "standard_elements", 100000)
    formation = tuple(
        StateRecord(
            state.id,
            state,
            properties={"enthalpy_formation_eV": _prop(value, formation_reference=reference)},
        )
        for state, value in ((neutral, 0), (ion, -1))
    )
    unsupported = _evaluate(
        reaction, (neutral, ion), records=formation, relations=(invalid,), energy=1
    )
    delta = unsupported.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value is None
    assert unsupported.reaction_assessments[reaction.id]["energy"].verdict == "unknown"
    assert {
        item.target for item in delta.requirements if item.responsibility == "source_review"
    } == {invalid.id, neutral.id, ion.id}
    assert unsupported.calculation_sources[invalid.id] == invalid

    independent = StateRecord(
        neutral.id,
        neutral,
        properties={
            "ionization_energy_eV": _prop(15, definition="adiabatic", related_state=ion.id)
        },
        record_id="ground-ionization",
    )
    supported = _evaluate(
        reaction, (neutral, ion), records=(*formation, independent), relations=(invalid,), energy=1
    )
    delta = supported.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value == 15
    assert not delta.alternatives
    assert supported.reaction_assessments[reaction.id]["energy"].verdict == "fail"


def test_dissociative_attachment_uses_specific_d0_and_fragment_ea_without_absolute_hf():
    f2 = candidate_state({"F": 2}, 0)
    f = candidate_state({"F": 1}, 0)
    fm = candidate_state({"F": 1}, -1)
    cut = _reaction("cut", [f2.id], [f.id, f.id], "neutral")
    d0 = ReactionRecord(
        "D0",
        cut.equation_key,
        "neutral",
        "dissociation",
        (f2, f),
        channel_scope="energy_relation",
        energy_properties={"delta_e_eV": _prop(2, definition="products_minus_reactants")},
    )
    # A dissociation energy relation is usable in a cycle without asserting an
    # uninduced molecular dissociation event in the candidate network.
    source = EvidenceCatalog(reaction_records=(d0,))
    assert not source.attested_candidates(())
    atom = StateRecord(f.id, f, properties={"electron_affinity_eV": _prop(3, definition="atomic")})
    parent = StateRecord(
        f2.id, f2, properties={"electron_affinity_eV": _prop(-1, definition="adiabatic")}
    )
    reaction = _reaction("DEA", ["e", f2.id], [fm.id, f.id], process="dissociative_attachment")
    result = _evaluate(reaction, (f2, f, fm), (atom, parent), (d0,), energy=0)
    calculations = result.thermochemical_calculations[reaction.id]
    delta = calculations["state_energy_difference_eV"]
    assert delta.value == -1
    assert {item["quantity"] for item in delta.inputs} == {"delta_e_eV", "electron_affinity_eV"}
    assert any(
        item["target"] == f.id
        for item in delta.inputs
        if item["quantity"] == "electron_affinity_eV"
    )
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "pass"
    assert result.reaction_assessments[reaction.id]["reaction_evidence"].verdict == "unknown"
    assert "D0" in result.calculation_sources


def test_charged_fragment_transfer_can_use_association_written_endpoint_relations():
    donor = candidate_state({"B": 1, "F": 4}, -1)
    base = candidate_state({"B": 1, "F": 3}, 0)
    acceptor = candidate_state({"Si": 1, "F": 4}, 0)
    adduct = candidate_state({"Si": 1, "F": 5}, -1)
    fluoride = candidate_state({"F": 1}, -1)
    records = []
    for identifier, left, right, value in (
        ("donor_association", base, donor, -4),
        ("acceptor_association", acceptor, adduct, -6),
    ):
        association = _reaction(
            identifier, [left.id, fluoride.id], [right.id], "ion", "net_association"
        )
        records.append(
            ReactionRecord(
                identifier,
                association.equation_key,
                "ion",
                "net_association",
                (left, fluoride, right),
                channel_scope="energy_relation",
                energy_properties={
                    "delta_e_eV": _prop(
                        value,
                        definition="products_minus_reactants",
                        formation_reference=FormationReference(0),
                    )
                },
            )
        )
    transfer = _reaction(
        "transfer", [donor.id, acceptor.id], [base.id, adduct.id], "ion", "net_group_transfer"
    )
    result = _evaluate(transfer, (donor, base, acceptor, adduct), relations=records, energy=0)
    delta = result.thermochemical_calculations[transfer.id]["state_energy_difference_eV"]
    assert delta.value == -2
    assert delta.operation == "two_dissociation_transfer_cycle"
    assert {term["record_id"]: term["coefficient"] for term in delta.inputs} == {
        "donor_association": -1,
        "acceptor_association": 1,
    }
    assert result.reaction_assessments[transfer.id]["energy"].verdict == "pass"

    finite_temperature = replace(
        records[0],
        energy_properties={
            "delta_e_eV": replace(
                records[0].energy_properties["delta_e_eV"],
                formation_reference=FormationReference(298.15),
            )
        },
    )
    result = _evaluate(
        transfer, (donor, base, acceptor, adduct), relations=(finite_temperature, records[1])
    )
    assert (
        result.thermochemical_calculations[transfer.id]["state_energy_difference_eV"].value is None
    )


def test_zero_k_endpoint_difference_does_not_require_unused_pressure_and_keeps_sources():
    f2, f = candidate_state({"F": 2}, 0), candidate_state({"F": 1}, 0)
    reference = FormationReference(0, "standard_elements")
    records = tuple(
        StateRecord(
            s.id,
            s,
            record_id="hf:" + s.id,
            properties={"enthalpy_formation_eV": _prop(v, formation_reference=reference)},
        )
        for s, v in ((f2, 0), (f, 2))
    )
    reaction = _reaction("split", ["e", f2.id], ["e", f.id, f.id])
    result = _evaluate(reaction, (f2, f), records, energy=3)
    delta = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value == 4
    assert sorted(item["coefficient"] for item in delta.inputs) == [-1, 2]
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "fail"
    assert delta.conditions == {"reference_temperature_K": 0}


def test_collective_formation_value_does_not_identify_one_collision_state():
    collective = candidate_state({"F": 2}, 0, "composition", resolution="lumped")
    atom = candidate_state({"F": 1}, 0)
    reference = FormationReference(0, "standard_elements", 100000)
    records = tuple(
        StateRecord(
            s.id, s, properties={"enthalpy_formation_eV": _prop(v, formation_reference=reference)}
        )
        for s, v in ((collective, 0), (atom, 2))
    )
    reaction = _reaction("collective", ["e", collective.id], ["e", atom.id, atom.id])
    result = _evaluate(reaction, (collective, atom), records, energy=20)
    calculated = result.thermochemical_calculations[reaction.id]
    assert calculated["delta_h_eV"].value == 4
    assert calculated["state_energy_difference_eV"].value is None
    assert {
        need.responsibility for need in calculated["state_energy_difference_eV"].requirements
    } >= {"identity"}


def test_lab_self_collision_cancels_equal_mass_and_com_pair_scope_precedes_missing_data():
    ar = candidate_state({"Ar": 1}, 0)
    elastic = _reaction("self", [ar.id, ar.id], [ar.id, ar.id], "neutral", "elastic")
    result = evaluate(
        CandidateSet({ar.id: ar}, {elastic.id: elastic}),
        EvidenceCatalog(),
        Conditions(
            collision_energy_eV=10,
            collision_energy_frame="lab",
            target_at_rest=True,
            projectile_state=ar.id,
            target_state=ar.id,
        ),
        DataSelection(
            quantities={"delta_e_eV": QuantitySelection(mode="only", providers=("selected",))}
        ),
    )
    calculations = result.thermochemical_calculations[elastic.id]
    assert calculations["state_energy_difference_eV"].value == 0
    margin = calculations["collision_energy_margin_eV"]
    assert margin.value == 5
    assert margin.inputs[1]["operation"] == "equal_represented_mass_cancellation"
    h2, h = candidate_state({"H": 2}, 0), candidate_state({"H": 1}, 0)
    other = _reaction(
        "other", [ar.id, h2.id], [ar.id, h.id, h.id], "neutral", "collision_induced_dissociation"
    )
    result = evaluate(
        CandidateSet({s.id: s for s in (ar, h2, h)}, {other.id: other}),
        EvidenceCatalog(),
        Conditions(
            collision_energy_eV=10,
            collision_energy_frame="com",
            projectile_state=ar.id,
            target_state=ar.id,
        ),
    )
    assert result.reaction_assessments[other.id]["energy"].verdict == "not_applicable"
    assert result.reaction_assessments[other.id]["energy"].requirements == ()


def test_single_level_gap_uses_the_selected_equivalent_event_difference():
    ground = candidate_state({"Ar": 1}, 0)
    excited = candidate_state(ground.composition, 0, "resolved", label="upper")
    reaction = _reaction("excite", ["e", ground.id], ["e", excited.id], process="excitation")
    records = tuple(
        ReactionRecord(
            name,
            reaction.equation_key,
            "electron",
            "excitation",
            (ground, excited),
            channel_scope="energy_relation",
            energy_properties={"delta_e_eV": _prop(value, definition="products_minus_reactants")},
        )
        for name, value in (("selected", 2), ("other", 3))
    )
    result = evaluate(
        CandidateSet(
            {state.id: state for state in (ground, excited, electron_state())},
            {reaction.id: reaction},
        ),
        EvidenceCatalog(reaction_records=records),
        Conditions(),
        DataSelection(quantities={"delta_e_eV": QuantitySelection(record="selected")}),
    )
    calculations = result.thermochemical_calculations[reaction.id]
    event = calculations["state_energy_difference_eV"]
    gap = calculations["level_gap_1_eV"]
    assert gap.value == event.value == 2
    assert gap.inputs == (
        {"operation": "level_state_pair", "initial": ground.id, "final": excited.id},
        {"calculation": "state_energy_difference_eV", "coefficient": 1.0},
    )
    assert event.inputs[0]["record_id"] == "selected"
    assert any(item["value"] == 3 for item in event.alternatives)


def test_an_inverted_ground_level_order_cannot_support_excitation():
    ground = candidate_state({"Ar": 1}, 0)
    upper = candidate_state(ground.composition, 0, "resolved", label="upper")
    excitation = _reaction("excitation", ["e", ground.id], ["e", upper.id], process="excitation")
    declaration = ReactionRecord(
        "negative-gap",
        excitation.equation_key,
        excitation.family,
        excitation.process,
        (ground, upper),
        channel_scope="energy_relation",
        energy_properties={"delta_e_eV": _prop(-2, definition="products_minus_reactants")},
    )
    result = _evaluate(excitation, (ground, upper), relations=(declaration,), energy=0)
    assert (
        result.thermochemical_calculations[excitation.id]["state_energy_difference_eV"].value
        is None
    )
    assert result.reaction_assessments[excitation.id]["energy"].verdict == "unknown"
    difference = result.thermochemical_calculations[excitation.id]["state_energy_difference_eV"]
    assert any(
        item.target == declaration.id and item.responsibility == "source_review"
        for item in difference.requirements
    )
    assert result.calculation_sources[declaration.id] == declaration


def test_penning_interval_and_endpoint_use_the_same_scoped_relative_energy():
    donor = candidate_state({"Ar": 1}, 0, "resolved", label="upper")
    relaxed = candidate_state(donor.composition, 0)
    target = candidate_state({"Ne": 1}, 0)
    ion = candidate_state(target.composition, 1)
    reaction = _reaction(
        "penning",
        [donor.id, target.id],
        [relaxed.id, ion.id, "e"],
        family="neutral",
        process="penning_ionization",
    )
    candidates = CandidateSet(
        {state.id: state for state in (donor, relaxed, target, ion, electron_state())},
        {reaction.id: reaction},
    )
    catalog = EvidenceCatalog(
        state_records=(
            StateRecord(
                donor.id,
                donor,
                properties={
                    "excitation_energy_eV": _prop(4),
                    "mass_amu": Property(40, "u", tier="reviewed"),
                },
            ),
            StateRecord(
                target.id,
                target,
                properties={
                    "ionization_energy_eV": _prop(10, definition="atomic"),
                    "mass_amu": Property(20, "u", tier="reviewed"),
                },
            ),
        )
    )
    laboratory = Conditions(
        collision_energy_eV=10,
        collision_energy_frame="lab",
        target_at_rest=True,
        projectile_state=donor.id,
        target_state=target.id,
    )
    explicit = evaluate(candidates, catalog, laboratory)
    verdicts = explicit.reaction_assessments[reaction.id]
    assert verdicts["thermochemistry"].verdict == verdicts["energy"].verdict == "fail"
    margin = explicit.thermochemical_calculations[reaction.id]["collision_energy_margin_eV"]
    assert margin.value == pytest.approx(10 / 3 - 6)
    unframed = evaluate(candidates, catalog, replace(laboratory, collision_energy_frame=None))
    assert unframed.reaction_assessments[reaction.id]["thermochemistry"].verdict == "unknown"
    assert unframed.reaction_assessments[reaction.id]["energy"].verdict == "unknown"


def test_exact_reverse_relation_can_be_selected_and_traced_after_save(tmp_path):
    ground = candidate_state({"Ar": 1}, 0)
    upper = candidate_state(ground.composition, 0, "resolved", label="upper")
    declarations = []
    for name, initial, final, value in (
        ("forward-source", ground, upper, 6),
        ("reverse-source", upper, ground, -4),
    ):
        channel = _reaction(name, [initial.id], [final.id], "neutral", "level_transfer")
        declarations.append(
            ReactionRecord(
                name,
                channel.equation_key,
                channel.family,
                channel.process,
                (initial, final),
                channel_scope="energy_relation",
                energy_properties={
                    "delta_e_eV": _prop(
                        value,
                        definition="products_minus_reactants",
                        provenance=SourceRef(provider=name),
                    ),
                },
            )
        )
    catalog = EvidenceCatalog(reaction_records=tuple(declarations))
    case = Case(
        "reverse-written state gap",
        ("Ar",),
        supplies=("e",),
        limits=Limits(max_depth=1, max_atoms=1),
        conditions=Conditions(collision_energy_eV=5, collision_energy_frame="com"),
    )
    baseline = document(analyze(case, catalog))
    excitation = next(
        row
        for row in baseline["reactions"]
        if row["process"] == "excitation" and upper.id in {t["species"] for t in row["products"]}
    )
    target = excitation["id"]
    assert excitation["assessments"]["energy"]["verdict"] == "unknown"
    reverse = "reverse-source"
    for policy in (QuantitySelection(record=reverse), QuantitySelection(providers=(reverse,))):
        picked = replace(
            case, data_selection=DataSelection(targets={target: {"delta_e_eV": policy}})
        )
        write(tmp_path, analyze(picked, catalog))
        saved = read(tmp_path, verify_views=True)
        row = next(row for row in saved["reactions"] if row["id"] == target)
        gap = row["thermochemical_calculations"]["state_energy_difference_eV"]
        assert gap["value"] == 4
        assert row["assessments"]["energy"]["verdict"] == "pass"
        assert {offer["value"] for offer in gap["alternatives"]} == {6}
        selected = next(
            row
            for row in registered_records(saved, target, "delta_e_eV")["records"]
            if row["id"] == reverse
        )
        assert selected["energy_properties"]["delta_e_eV"]["value"] == -4
        assert selected["energy_role"] == "direct"
        (use,) = selected["energy_uses"]
        assert (use["operation"], use["coefficient"]) == ("reversed_state_relation", -1)

    incompatible = QuantitySelection(mode="only", record=reverse, providers=("forward-source",))
    picked = replace(
        case, data_selection=DataSelection(targets={target: {"delta_e_eV": incompatible}})
    )
    with pytest.raises(ValueError, match="contradicts only restrictions"):
        analyze(picked, catalog)


def test_saved_stepwise_ionization_lists_state_inputs_of_the_endpoint_difference():
    neutral = candidate_state({"Ar": 1}, 0)
    excited = candidate_state(neutral.composition, 0, "resolved", label="upper")
    records = (
        StateRecord(
            neutral.id,
            neutral,
            record_id="ground-source",
            properties={
                "ionization_energy_eV": _prop(10, definition="atomic"),
                "mass_amu": Property(40, "amu", tier="reviewed"),
            },
        ),
        StateRecord(
            excited.id,
            excited,
            record_id="level-source",
            properties={"excitation_energy_eV": _prop(4, related_state=neutral.id)},
        ),
    )
    case = Case(
        "stepwise ionization",
        ("Ar",),
        supplies=("e", excited.id),
        limits=Limits(max_depth=1),
        conditions=Conditions(collision_energy_eV=8, collision_energy_frame="com"),
    )
    saved = document(analyze(case, EvidenceCatalog(state_records=records)))
    reaction = next(
        item
        for item in saved["reactions"]
        if item["process"] == "ionization"
        and {term["species"] for term in item["reactants"]} == {"e", excited.id}
    )
    assert reaction["thermochemical_calculations"]["state_energy_difference_eV"]["value"] == 6
    listed = registered_records(saved, reaction["id"], "delta_e_eV")["records"]
    assert all(item["energy_role"] == "derived" for item in listed)
    assert {
        item["record_id"]: (item["record_target"], set(item["properties"])) for item in listed
    } == {
        "ground-source": (neutral.id, {"ionization_energy_eV"}),
        "level-source": (excited.id, {"excitation_energy_eV"}),
    }
    assert {item["record_id"]: item["energy_uses"][0]["coefficient"] for item in listed} == {
        "ground-source": 1,
        "level-source": -1,
    }


def test_two_level_changes_keep_signed_gaps_independent_of_event_total():
    ground = candidate_state({"Ar": 1}, 1)
    lower, upper = (
        candidate_state(ground.composition, 1, "resolved", label=label, resolution="resolved")
        for label in ("lower", "upper")
    )
    rotor = candidate_state({"H": 2}, 0)
    j1 = candidate_state(rotor.composition, 0, "rotational", label="J1", resolution="resolved")
    states = (ground, lower, upper, rotor, j1)
    records = tuple(
        StateRecord(
            state.id,
            state,
            properties={"excitation_energy_eV": _prop(value, related_state=reference.id)},
        )
        for state, value, reference in ((lower, 2, ground), (upper, 5, ground), (j1, 1, rotor))
    )
    reaction = _reaction(
        "transfer",
        [upper.id, rotor.id],
        [lower.id, j1.id],
        "ion",
        "level_transfer",
        transformation={
            "kind": "two_level_transition",
            "initial": [upper.id, rotor.id],
            "final": [lower.id, j1.id],
        },
    )
    result = _evaluate(reaction, states, records)
    calculations = result.thermochemical_calculations[reaction.id]
    # Ar+'s two offsets have the same reference. Its neutral ground and IE
    # are absent, while H2 moves in the opposite direction.
    assert calculations["state_energy_difference_eV"].value == -2
    assert calculations["level_gap_1_eV"].value == -3
    assert calculations["level_gap_2_eV"].value == 1
    assert calculations["level_gap_1_eV"].inputs[0] == {
        "operation": "level_state_pair",
        "initial": upper.id,
        "final": lower.id,
    }
    assert [term["coefficient"] for term in calculations["level_gap_1_eV"].inputs[1:]] == [-1, 1]

    # The chosen direct event value does not tell us which participant gained
    # energy. Remove one of the ion offsets while retaining the rotor's gap.
    direct = ReactionRecord(
        "event-total",
        reaction.equation_key,
        "ion",
        "level_transfer",
        states,
        channel_scope="energy_relation",
        energy_properties={"delta_e_eV": _prop(4, definition="products_minus_reactants")},
    )
    selected = evaluate(
        CandidateSet({state.id: state for state in states}, {reaction.id: reaction}),
        EvidenceCatalog(records[1:], (direct,)),
        Conditions(collision_energy_eV=3, collision_energy_frame="com"),
        DataSelection(quantities={"delta_e_eV": QuantitySelection(record=direct.id)}),
    )
    calculations = selected.thermochemical_calculations[reaction.id]
    assert calculations["state_energy_difference_eV"].value == 4
    assert calculations["level_gap_1_eV"].value is None
    assert calculations["level_gap_2_eV"].value == 1


def test_generated_dissociative_quench_combines_a_direct_level_gap_and_d0(tmp_path):
    ground = candidate_state({"Ar": 1}, 0)
    excited = candidate_state(ground.composition, 0, "resolved", label="upper")
    h2, h = candidate_state({"H": 2}, 0), candidate_state({"H": 1}, 0)
    states = (ground, excited, h2, h)
    gap = _reaction("argon-gap", [excited.id], [ground.id], "neutral", "level_transfer")
    cut = _reaction("hydrogen-d0", [h2.id], [h.id, h.id], "neutral")
    relations = tuple(
        ReactionRecord(
            item.id,
            item.equation_key,
            item.family,
            item.process,
            endpoints,
            channel_scope="energy_relation",
            energy_properties={"delta_e_eV": _prop(value, definition="products_minus_reactants")},
        )
        for item, value, endpoints in ((gap, -10, (ground, excited)), (cut, 4, (h2, h)))
    )
    case = Case(
        "quench",
        ("H2",),
        limits=Limits(max_depth=1),
        supplies=(excited.id,),
        conditions=Conditions(collision_energy_eV=0, collision_energy_frame="com"),
    )
    analysis = analyze(case, EvidenceCatalog(reaction_records=relations))
    saved = document(analysis)
    row = next(
        item
        for item in saved["reactions"]
        if item["process"] == "dissociation_with_level_transfer"
        and {term["species"] for term in item["reactants"]} == {h2.id, excited.id}
        and {term["species"] for term in item["products"]} == {ground.id, h.id}
    )
    calculations = row["thermochemical_calculations"]
    assert calculations["level_gap_1_eV"]["value"] == -10
    event = calculations["state_energy_difference_eV"]
    assert event["value"] == -6
    assert event["inputs"][0] == {"calculation": "level_gap_1_eV", "coefficient": 1.0}
    assert event["inputs"][1]["record_id"] == cut.id
    assert row["assessments"]["energy"]["verdict"] == "pass"
    listed = registered_records(saved, row["id"], "delta_e_eV")["records"]
    assert {item["id"]: item["energy_role"] for item in listed} == {
        gap.id: "derived",
        cut.id: "derived",
    }
    assert all(item["energy_uses"][0]["status"] == "selected" for item in listed)
    html = view(saved, tmp_path, "network").read_text(encoding="utf-8")
    match = re.search(r'<script id="network-data" type="application/json">(.*?)</script>', html)
    assert match is not None
    embedded = json.loads(match.group(1))
    channel = next(item for item in embedded["reactions"] if item["id"] == row["id"])
    assert {item["record_id"] for item in channel["calculation_uses"]} == {gap.id, cut.id}
    cut_ref = event["inputs"][1]["record_ref"]
    assert (
        embedded["calculation_sources"][cut.id][cut_ref]["energy_properties"]["delta_e_eV"]["value"]
        == 4
    )

    event["inputs"][1]["quantity"] = "mass_amu"
    saved["helper_views"] = {
        name: sha256(content.encode()).hexdigest() for name, content in csv_views(saved).items()
    }
    with pytest.raises(ValueError, match="absent scientific record, target or quantity"):
        validate(saved)

    measured_difference = ReactionRecord(
        "direct-quench",
        analysis.candidates.reactions[row["id"]].equation_key,
        "neutral",
        "dissociation_with_level_transfer",
        states,
        energy_properties={"delta_e_eV": _prop(-6, definition="products_minus_reactants")},
    )
    rerun = document(
        analyze(case, EvidenceCatalog(reaction_records=(*relations, measured_difference)))
    )
    by_id = {
        item["id"]: item for item in registered_records(rerun, row["id"], "delta_e_eV")["records"]
    }
    assert by_id[measured_difference.id]["energy_role"] == "direct"
    assert by_id[measured_difference.id]["energy_properties"]["delta_e_eV"]["value"] == -6
    assert by_id[cut.id]["energy_uses"][0]["status"] == "alternative"

    conflicting_d0 = replace(
        relations[1],
        id="other-d0",
        energy_properties={"delta_e_eV": _prop(5, definition="products_minus_reactants")},
    )
    reaction = analysis.candidates.reactions[row["id"]]
    # A false alternate mapping cannot erase the level pair of a valid one.
    valid = reaction.transformation
    wrong = {**valid, "collider_product": excited.id}
    reaction = replace(
        reaction, transformation={"kind": "alternatives", "alternatives": [wrong, valid]}
    )
    conflict = _evaluate(reaction, states, relations=(*relations, conflicting_d0), energy=0)
    calculations = conflict.thermochemical_calculations[reaction.id]
    assert calculations["level_gap_1_eV"].value == -10
    event = calculations["state_energy_difference_eV"]
    assert event.value is None
    assert {item["value"] for item in event.alternatives} == {-6, -5}


def test_vertical_ie_does_not_replace_adiabatic_state_difference():
    neutral = candidate_state({"H": 2}, 0)
    ion = candidate_state({"H": 2}, 1)
    reaction = _reaction("ionize", ["e", neutral.id], ["e", "e", ion.id], process="ionization")
    record = StateRecord(
        neutral.id, neutral, properties={"ionization_energy_eV": _prop(12, definition="vertical")}
    )
    result = _evaluate(reaction, (neutral, ion), (record,), energy=11)
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "unknown"

    adiabatic = replace(
        record, properties={"ionization_energy_eV": _prop(10, definition="adiabatic")}
    )
    result = _evaluate(reaction, (neutral, ion), (adiabatic,), energy=11)
    assert result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"].value == 10
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "pass"
    wrong_pair = replace(
        adiabatic,
        properties={
            "ionization_energy_eV": _prop(10, definition="adiabatic", related_state="He+@ground")
        },
    )
    result = _evaluate(reaction, (neutral, ion), (wrong_pair,), energy=11)
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "unknown"


def test_preferred_input_is_used_and_unselected_complete_value_remains_visible():
    neutral, ion = candidate_state({"Ar": 1}, 0), candidate_state({"Ar": 1}, 1)
    reaction = _reaction("IE", ["e", neutral.id], ["e", "e", ion.id], process="ionization")
    records = tuple(
        StateRecord(
            neutral.id,
            neutral,
            properties={"ionization_energy_eV": _prop(value, definition="atomic", method=method)},
        )
        for value, method in ((10, "measured"), (12, "calculated"))
    )
    result = evaluate(
        CandidateSet({s.id: s for s in (neutral, ion, electron_state())}, {reaction.id: reaction}),
        EvidenceCatalog(records),
        Conditions(collision_energy_eV=11, collision_energy_frame="com"),
        DataSelection(
            quantities={
                "ionization_energy_eV": QuantitySelection(methods=("measured", "calculated"))
            }
        ),
    )
    difference = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert difference.value == 10
    assert difference.inputs[0]["method"] == "measured"
    assert any(item["value"] == 12 for item in difference.alternatives)


@pytest.mark.parametrize("scale", [0.5, 2.0])
def test_scaled_net_equation_is_not_compared_to_one_collision_energy(scale):
    neutral, ion = candidate_state({"Ar": 1}, 0), candidate_state({"Ar": 1}, 1)
    reaction = _reaction("scaled", ["e", neutral.id], ["e", "e", ion.id], process="ionization")
    reaction = replace(
        reaction,
        reactants=tuple(Term(t.species, t.n * scale) for t in reaction.reactants),
        products=tuple(Term(t.species, t.n * scale) for t in reaction.products),
    )
    record = StateRecord(
        neutral.id, neutral, properties={"ionization_energy_eV": _prop(10, definition="atomic")}
    )
    result = _evaluate(reaction, (neutral, ion), (record,), energy=15)
    assert (
        result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"].value
        == 10 * scale
    )
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "unknown"


def test_direct_reaction_value_does_not_hide_a_complete_transfer_cycle():
    rh, r = candidate_state({"Si": 1, "H": 4}, 0), candidate_state({"Si": 1, "H": 3}, 0)
    h, x, xh = (
        candidate_state({"H": 1}, 0),
        candidate_state({"F": 1}, 0),
        candidate_state({"F": 1, "H": 1}, 0),
    )
    reaction = _reaction("transfer", [rh.id, x.id], [r.id, xh.id], "neutral", "net_group_transfer")
    raw = [
        (reaction, 0),
        (_reaction("cut1", [rh.id], [r.id, h.id], "neutral"), 10),
        (_reaction("cut2", [xh.id], [x.id, h.id], "neutral"), 1),
    ]
    states = (rh, r, h, x, xh)
    relations = tuple(
        ReactionRecord(
            rr.id,
            rr.equation_key,
            "neutral",
            rr.process,
            states,
            energy_properties={"delta_e_eV": _prop(v, definition="products_minus_reactants")},
        )
        for rr, v in raw
    )
    result = _evaluate(reaction, states, relations=relations, energy=20)
    delta = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value is None
    assert {entry["value"] for entry in delta.alternatives} == {0, 9}
    margin = result.thermochemical_calculations[reaction.id]["collision_energy_margin_eV"]
    assert margin.value is None
    assert not margin.alternatives
    assert margin.requirements == delta.requirements
    for policy in (QuantitySelection(), QuantitySelection(providers=("absent",))):
        unresolved = evaluate(
            CandidateSet({s.id: s for s in states}, {reaction.id: reaction}),
            EvidenceCatalog(reaction_records=relations),
            Conditions(collision_energy_eV=20, collision_energy_frame="com"),
            DataSelection(quantities={"delta_e_eV": policy}),
        )
        assert (
            unresolved.thermochemical_calculations[reaction.id]["state_energy_difference_eV"].value
            is None
        )
        assert unresolved.reaction_assessments[reaction.id]["energy"].verdict == "unknown"
    selected = evaluate(
        CandidateSet({s.id: s for s in states}, {reaction.id: reaction}),
        EvidenceCatalog(reaction_records=relations),
        Conditions(collision_energy_eV=20, collision_energy_frame="com"),
        DataSelection(quantities={"delta_e_eV": QuantitySelection(record="transfer")}),
    )
    delta = selected.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert delta.value == 0
    assert any(entry["value"] == 9 for entry in delta.alternatives)

    direct = tuple(
        replace(
            relations[0],
            id=provider,
            energy_properties={
                "delta_e_eV": _prop(
                    value,
                    definition="products_minus_reactants",
                    provenance=SourceRef(provider=provider),
                ),
            },
        )
        for provider, value in (("first", 0), ("second", 9))
    )
    for providers in (("first", "second"), ("second", "first")):
        allowed = evaluate(
            CandidateSet({s.id: s for s in states}, {reaction.id: reaction}),
            EvidenceCatalog(reaction_records=direct),
            Conditions(collision_energy_eV=20, collision_energy_frame="com"),
            DataSelection(
                quantities={"delta_e_eV": QuantitySelection(mode="only", providers=providers)}
            ),
        )
        comparison = allowed.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
        assert comparison.value is None
        assert {entry["value"] for entry in comparison.alternatives} == {0, 9}


def test_collision_mass_keeps_selection_review_and_missing_responsibilities():
    neutral = candidate_state({"Ar": 1}, 0)
    source = StateRecord(
        neutral.id,
        neutral,
        properties={
            "ionization_energy_eV": _prop(15, definition="atomic"),
        },
    )
    known = replace(
        source,
        properties=source.properties
        | {
            "mass_amu": Property(40, "u", tier="reviewed"),
        },
    )
    unreviewed = replace(
        known,
        properties=known.properties
        | {
            "mass_amu": Property(40, "u"),
        },
    )
    request = RequestedReaction("e + Ar -> Ar+ + 2 e", "ionization")
    case = Case(
        "lab Ar",
        ("Ar",),
        Conditions(electron_energy_eV=17, target_at_rest=True),
        supplies=("e",),
        reactions=(request,),
        limits=Limits(max_depth=1, max_atoms=1),
    )
    restriction = DataSelection(
        targets={neutral.id: {"mass_amu": QuantitySelection(record="absent")}}
    )
    for record, selection, responsibility in (
        (source, DataSelection(), "source_information"),
        (unreviewed, DataSelection(), "source_review"),
        (known, restriction, "source_selection"),
        (known, DataSelection(), None),
    ):
        result = analyze(replace(case, data_selection=selection), EvidenceCatalog((record,)))
        margin = result.evaluation.thermochemical_calculations[request.candidate.id][
            "collision_energy_margin_eV"
        ]
        if responsibility is None:
            assert margin.status == "computed"
        else:
            assert margin.status == "unavailable"
            assert [
                (item.target, item.quantity, item.responsibility) for item in margin.requirements
            ] == [
                (neutral.id, "mass_amu", responsibility),
            ]


def test_pa_and_gb_are_separate_finite_temperature_outputs_not_collision_inputs():
    h2, h3 = candidate_state({"H": 2}, 0), candidate_state({"H": 3}, 1)
    nh3, nh4 = candidate_state({"N": 1, "H": 3}, 0), candidate_state({"N": 1, "H": 4}, 1)
    reference = FormationReference(298.15, standard_pressure_Pa=100000)
    records = tuple(
        StateRecord(
            base.id,
            base,
            properties={
                "proton_affinity_eV": _prop(
                    pa, related_state=adduct.id, formation_reference=reference
                ),
                "gas_basicity_eV": _prop(
                    gb, related_state=adduct.id, formation_reference=reference
                ),
            },
        )
        for base, adduct, pa, gb in ((h2, h3, 4.0, 3.0), (nh3, nh4, 8.0, 6.0))
    )
    reaction = _reaction("PT", [h3.id, nh3.id], [h2.id, nh4.id], "ion", "net_group_transfer")
    result = _evaluate(reaction, (h2, h3, nh3, nh4), records, energy=0)
    calculations = result.thermochemical_calculations[reaction.id]
    assert calculations["proton_transfer_delta_h_eV"].value == -4
    assert calculations["proton_transfer_delta_g_eV"].value == -3
    assert calculations["state_energy_difference_eV"].value is None
    assert result.reaction_assessments[reaction.id]["energy"].verdict == "unknown"

    missing_pressure = tuple(
        replace(
            record,
            properties={
                **record.properties,
                "gas_basicity_eV": replace(
                    record.properties["gas_basicity_eV"],
                    formation_reference=FormationReference(298.15),
                ),
            },
        )
        for record in records
    )
    result = _evaluate(reaction, (h2, h3, nh3, nh4), missing_pressure, energy=0)
    assert result.thermochemical_calculations[reaction.id]["proton_transfer_delta_h_eV"].value == -4
    gb = result.thermochemical_calculations[reaction.id]["proton_transfer_delta_g_eV"]
    assert gb.value is None
    assert gb.requirements[0].quantity.endswith("standard_pressure_Pa")

    partial = _evaluate(reaction, (h2, h3, nh3, nh4), records[:1], energy=0)
    pa = partial.thermochemical_calculations[reaction.id]["proton_transfer_delta_h_eV"]
    assert pa.status == "unavailable"
    (missing,) = pa.requirements
    assert (missing.responsibility, missing.target, missing.quantity) == (
        "source_information",
        nh3.id,
        "proton_affinity_eV",
    )
    assert nh4.id in missing.reason


def test_proton_transfer_preserves_conflicting_records_and_independent_conditions():
    h2, h3 = candidate_state({"H": 2}, 0), candidate_state({"H": 3}, 1)
    nh3, nh4 = candidate_state({"N": 1, "H": 3}, 0), candidate_state({"N": 1, "H": 4}, 1)
    records = tuple(
        StateRecord(
            base.id,
            base,
            record_id=record_id,
            properties={
                "proton_affinity_eV": _prop(
                    pa, related_state=adduct.id, formation_reference=FormationReference(298.15)
                ),
                "gas_basicity_eV": _prop(
                    gb,
                    related_state=adduct.id,
                    formation_reference=FormationReference(310, standard_pressure_Pa=100000),
                ),
            },
        )
        for base, adduct, record_id, pa, gb in (
            (h2, h3, "hydrogen", 4, 3),
            (nh3, nh4, "ammonia-first", 8, 6),
            (nh3, nh4, "ammonia-second", 9, 6),
        )
    )
    case = Case(
        "finite-temperature transfer",
        ("H2", "NH3"),
        supplies=(h3.id,),
        limits=Limits(max_depth=1, max_atoms=5),
    )
    catalog = EvidenceCatalog(state_records=records)

    def transfer(request):
        payload = document(analyze(request, catalog))
        row = next(
            row
            for row in payload["reactions"]
            if row["process"] == "net_group_transfer"
            and {term["species"] for term in row["reactants"]} == {h3.id, nh3.id}
            and {term["species"] for term in row["products"]} == {h2.id, nh4.id}
        )
        return payload, row

    saved, row = transfer(case)
    result = row["thermochemical_calculations"]
    pa = result["proton_transfer_delta_h_eV"]
    assert pa["status"] == "unavailable"
    assert pa["requirements"][0]["responsibility"] == "source_selection"
    assert {item["value"] for item in pa["alternatives"]} == {-4, -5}
    assert all(
        [term["coefficient"] for term in item["inputs"]] == [1, -1] for item in pa["alternatives"]
    )
    assert result["proton_transfer_delta_g_eV"]["value"] == -3
    assert result["state_energy_difference_eV"]["value"] is None
    pa_sources = registered_records(saved, row["id"], "proton_affinity_eV")["records"]
    assert {item["record_id"] for item in pa_sources} == {
        "hydrogen",
        "ammonia-first",
        "ammonia-second",
    }
    assert all(set(item["properties"]) == {"proton_affinity_eV"} for item in pa_sources)
    assert all(use["status"] == "alternative" for item in pa_sources for use in item["energy_uses"])

    selection = DataSelection(
        targets={nh3.id: {"proton_affinity_eV": QuantitySelection(record="ammonia-first")}}
    )
    _, row = transfer(replace(case, data_selection=selection))
    result = row["thermochemical_calculations"]
    pa = result["proton_transfer_delta_h_eV"]
    assert pa["value"] == -4
    assert [item["value"] for item in pa["alternatives"]] == [-5]
    assert row["thermochemistry"]["proton_transfer_delta_h_reference_temperature_K"] == 298.15
    assert row["thermochemistry"]["proton_transfer_delta_g_reference_temperature_K"] == 310
    assert row["thermochemistry"]["proton_transfer_delta_g_standard_pressure_Pa"] == 100000
    assert row["assessments"]["energy"]["verdict"] == "unknown"


def test_capture_distinguishes_unspecified_exchange_and_an_unsupported_model():
    fluorine, anion = candidate_state({"F": 1}, 0), candidate_state({"F": 1}, -1)
    record = StateRecord(
        fluorine.id,
        fluorine,
        properties={"electron_affinity_eV": _prop(3, definition="atomic")},
    )
    for stabilization, work in (
        ("unspecified", ("source_information", "capture_energy_exchange")),
        ("radiative", ("external_models", "collision_stabilization_model")),
    ):
        reaction = _reaction(
            "capture",
            ["e", fluorine.id],
            [anion.id],
            process="attachment",
            stabilization=stabilization,
        )
        result = _evaluate(reaction, (fluorine, anion), (record,), energy=5)
        calculations = result.thermochemical_calculations[reaction.id]
        assert calculations["state_energy_difference_eV"].value == -3
        margin = calculations["collision_energy_margin_eV"]
        assert margin.status == "unavailable"
        energy = result.reaction_assessments[reaction.id]["energy"]
        assert energy.verdict == "unknown"
        (requirement,) = energy.requirements
        assert (requirement.responsibility, requirement.quantity) == work
        assert margin.requirements == energy.requirements


def test_nonbinding_or_zero_ea_does_not_create_a_ground_anion_energy_anchor():
    neutral, anion = candidate_state({"Ar": 1}, 0), candidate_state({"Ar": 1}, -1)
    reaction = _reaction(
        "capture", ["e", neutral.id], [anion.id], process="attachment", stabilization="isolated"
    )
    positive = StateRecord(
        neutral.id, neutral, properties={"electron_affinity_eV": _prop(1, definition="atomic")}
    )
    unbound = replace(
        positive,
        properties={
            "electron_affinity_eV": Property(
                None, "eV", tier="reviewed", definition="atomic", qualifier="unbound"
            )
        },
    )
    for records in (
        (positive, unbound),
        (replace(positive, properties={"electron_affinity_eV": _prop(0, definition="atomic")}),),
    ):
        result = _evaluate(reaction, (neutral, anion), records, energy=0)
        assert (
            result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"].value
            is None
        )
        assert result.reaction_assessments[reaction.id]["energy"].verdict == "unknown"


@pytest.mark.parametrize("route", ["formation", "direct"])
def test_formal_energy_does_not_establish_a_bound_capture_endpoint(route):
    neutral, anion = candidate_state({"Ar": 1}, 0), candidate_state({"Ar": 1}, -1)
    capture = _reaction(
        "formal_capture",
        ["e", neutral.id],
        [anion.id],
        process="attachment",
        stabilization="isolated",
    )
    reference = FormationReference(0, "standard_elements")
    formation = (
        tuple(
            StateRecord(
                state.id,
                state,
                properties={"enthalpy_formation_eV": _prop(0, formation_reference=reference)},
            )
            for state in (neutral, anion)
        )
        if route == "formation"
        else ()
    )
    direct = (
        (
            ReactionRecord(
                "formal_energy",
                capture.equation_key,
                capture.family,
                capture.process,
                (neutral, anion),
                channel_scope="energy_relation",
                energy_properties={"delta_e_eV": _prop(0, definition="products_minus_reactants")},
            ),
        )
        if route == "direct"
        else ()
    )
    negative_ea = StateRecord(
        neutral.id,
        neutral,
        record_id="negative_ea",
        properties={"electron_affinity_eV": _prop(-1, definition="atomic")},
    )
    unbound_state = StateRecord(
        anion.id,
        anion,
        record_id="unbound_identity",
        existence="unbound",
        existence_source="explicit ground-state nonbinding evidence",
        tier="reviewed",
    )
    confirmed_state = replace(unbound_state, existence="confirmed")
    for assertions in ((negative_ea,), (unbound_state,), (negative_ea, confirmed_state), ()):
        result = _evaluate(capture, (neutral, anion), (*formation, *assertions), direct, energy=0)
        calculations = result.thermochemical_calculations[capture.id]
        assert calculations["state_energy_difference_eV"].value == 0
        assert calculations["collision_energy_margin_eV"].value == 0
        energy = result.reaction_assessments[capture.id]["energy"]
        assert energy.verdict == "unknown"
        assert energy.dependencies
        claims = result.state_assessments[anion.id]
        binding_key = (
            "state"
            if claims["state"].proposition == "ground_anion_electron_binding"
            else "electron_binding"
        )
        assert claims[binding_key].verdict != "pass"
        if binding_key == "state":
            assert "electron_binding" not in claims
        assert all(key in result.state_assessments[state] for state, key in energy.dependencies)
        if assertions:
            assert {need.responsibility for need in energy.requirements} == {"external_models"}
    # A decisive energy mismatch remains a failure, irrespective of missing binding.
    result = _evaluate(capture, (neutral, anion), formation, direct, energy=1)
    assert result.thermochemical_calculations[capture.id]["collision_energy_margin_eV"].value == 1
    assert result.reaction_assessments[capture.id]["energy"].verdict == "fail"


def test_bound_endpoint_applicability_is_not_a_global_existence_gate():
    neutral, anion = candidate_state({"Ar": 1}, 0), candidate_state({"Ar": 1}, -1)
    detachment = _reaction("formal_detachment", ["e", anion.id], ["e", "e", neutral.id])
    reference = FormationReference(0, "standard_elements")
    formation = tuple(
        StateRecord(
            state.id,
            state,
            properties={"enthalpy_formation_eV": _prop(value, formation_reference=reference)},
        )
        for state, value in ((neutral, 1), (anion, 0))
    )
    transient = StateRecord(anion.id, anion, existence="transient")
    for assertions in ((), (transient,)):
        result = _evaluate(detachment, (neutral, anion), (*formation, *assertions), energy=2)
        assert result.reaction_assessments[detachment.id]["energy"].verdict == "pass"
    negative_ea = StateRecord(
        neutral.id,
        neutral,
        properties={"electron_affinity_eV": _prop(-1, definition="atomic")},
    )
    result = _evaluate(detachment, (neutral, anion), (*formation, negative_ea), energy=2)
    assert (
        result.thermochemical_calculations[detachment.id]["state_energy_difference_eV"].value == 1
    )
    assert (
        result.thermochemical_calculations[detachment.id]["collision_energy_margin_eV"].value == 1
    )
    assert result.reaction_assessments[detachment.id]["energy"].verdict == "unknown"
    # A canceled spectator does not demand its binding to decide energy identity.
    elastic = _reaction("identity", ["e", anion.id], ["e", anion.id], process="elastic")
    result = _evaluate(elastic, (neutral, anion), (negative_ea,), energy=2)
    assert result.reaction_assessments[elastic.id]["energy"].verdict == "pass"


def test_detachment_and_cid_do_not_pass_from_particle_counts_alone():
    fm, f, fp = (candidate_state({"F": 1}, q) for q in (-1, 0, 1))
    ar = candidate_state({"Ar": 1}, 0)
    arp = candidate_state({"Ar": 1}, 1)
    candidates = CandidateSet({s.id: s for s in (fm, f, fp, ar, arp, electron_state())}, {})
    wrong = _reaction(
        "wrong", [fm.id, ar.id], [fm.id, "e", arp.id], "ion", "collisional_detachment"
    )
    # The anion is unchanged; another particle loses an electron. Even a
    # separately balanced variant must not acquire the detachment label.
    assert assess_consistency(wrong, candidates).verdict == "fail"
    single = _reaction("elastic", [ar.id], [ar.id], "neutral", "elastic")
    assert assess_consistency(single, candidates).verdict == "fail"


@pytest.mark.parametrize(("unit", "value"), [("cm-1", 1000.0), ("Hz", 299792458.0 * 100000.0)])
def test_energy_units_keep_wavenumber_and_frequency_distinct(unit, value):
    from reactgen.units import energy_eV

    assert energy_eV(value, unit) == pytest.approx(0.12398419843320026)
