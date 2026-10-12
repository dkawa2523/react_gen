"""A disputed declaration affects only relations that consume its quantity.

The synthetic energies test logical dependencies, not empirical gas values.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import yamlio
from reactgen.assessment import assess_reaction_evidence, assess_thermochemistry
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state, electron_state
from reactgen.evidence import (
    EvidenceCatalog,
    ReactionEvidence,
    StateEvidence,
    reaction_record_candidate,
)
from reactgen.model import CandidateSet, ReactionCandidate, StateCandidate, Term
from reactgen.records import (
    FormationReference,
    Property,
    ReactionRecord,
    StateRecord,
    Thermo,
    reaction_record_payload,
)


def _state_record(state: StateCandidate, **energies: float) -> StateRecord:
    return StateRecord(
        state.id,
        state,
        properties={
            name: Property(
                value,
                "eV",
                tier="reviewed",
                definition="adiabatic"
                if name in {"ionization_energy_eV", "electron_affinity_eV"}
                else None,
                formation_reference=FormationReference(0, "standard_elements", 100000)
                if name == "enthalpy_formation_eV"
                else None,
            )
            for name, value in energies.items()
        },
    )


def _case(process: str):
    atom = candidate_state({"Ar": 1}, 0)
    cation = candidate_state({"Ar": 1}, 1)
    anion = candidate_state({"Ar": 1}, -1)
    target = candidate_state({"O": 2}, 0)
    product = candidate_state({"O": 2}, 1)
    excited = candidate_state({"Ar": 1}, 0, "electronic", label="level", resolution="resolved")
    electron = electron_state()
    states = (atom, cation, anion, target, product, excited, electron)
    evidence = {
        record.candidate.id: StateEvidence("exact", (record,))
        for record in (
            _state_record(atom, ionization_energy_eV=10.0, electron_affinity_eV=-1.0),
            _state_record(target, ionization_energy_eV=7.0),
            _state_record(excited, excitation_energy_eV=12.0),
        )
    }
    if process == "ionization":
        left, right, family, threshold, delta = (
            (Term(atom.id), Term(electron.id)),
            (Term(cation.id), Term(electron.id, 2)),
            "electron",
            11.0,
            10.0,
        )
    elif process == "elastic":
        left = right = (Term(atom.id), Term(electron.id))
        family, threshold, delta = "electron", 0.0, 0.0
    elif process == "penning_ionization":
        left, right, family, threshold, delta = (
            (Term(excited.id), Term(target.id)),
            (Term(atom.id), Term(product.id), Term(electron.id)),
            "neutral",
            0.0,
            -5.0,
        )
    elif process == "attachment":
        left, right, family, threshold, delta = (
            (Term(atom.id), Term(electron.id)),
            (Term(anion.id),),
            "electron",
            0.0,
            1.0,
        )
    else:
        resonant = process == "resonant_charge_exchange"
        left, right, family, threshold, delta = (
            (Term(cation.id), Term(atom.id if resonant else target.id)),
            (Term(atom.id), Term(cation.id if resonant else product.id)),
            "ion",
            0.0,
            0.0 if resonant else -3.0,
        )
    reaction = ReactionCandidate("energy-scope", left, right, family, process, "test", "test", 0)
    candidates = CandidateSet(states={state.id: state for state in states})
    record = ReactionRecord(
        "first-declaration",
        reaction.equation_key,
        family,
        process,
        states,
        energy_properties={
            "threshold_eV": Property(threshold, "eV", tier="reviewed"),
            "delta_e_eV": Property(delta, "eV", tier="reviewed"),
        },
        tier="reviewed",
        review_scope=("channel_assertion", "threshold_eV", "delta_e_eV"),
    )
    return reaction, candidates, evidence, record


@pytest.mark.parametrize(
    ("process", "baseline", "threshold_verdict", "delta_verdict"),
    [
        ("ionization", "pass", "unknown", "pass"),
        ("elastic", "pass", "unknown", "unknown"),
        ("charge_exchange", "pass", "pass", "unknown"),
        ("resonant_charge_exchange", "pass", "pass", "unknown"),
        ("penning_ionization", "pass", "pass", "pass"),
        ("attachment", "fail", "fail", "fail"),
    ],
)
@pytest.mark.parametrize("quantity", ["threshold_eV", "delta_e_eV"])
@pytest.mark.parametrize("same_id", [False, True])
def test_disagreement_is_local_to_the_relation_that_requires_the_quantity(
    process: str,
    baseline: str,
    threshold_verdict: str,
    delta_verdict: str,
    quantity: str,
    same_id: bool,
) -> None:
    reaction, candidates, states, record = _case(process)
    original, original_values = assess_thermochemistry(
        reaction, candidates, states, ReactionEvidence((record,)), Conditions()
    )
    assert original.verdict == baseline
    another = replace(
        record,
        id=record.id if same_id else "independent-declaration",
        energy_properties=record.energy_properties
        | {
            quantity: replace(
                record.energy_properties[quantity], value=getattr(record, quantity) + 1.0
            )
        },
    )
    results = []
    for ordered in ((record, another), (another, record)):
        evidence = ReactionEvidence(ordered)
        result, values = assess_thermochemistry(
            reaction, candidates, states, evidence, Conditions()
        )
        assert result.verdict == (
            threshold_verdict if quantity == "threshold_eV" else delta_verdict
        )
        output = "threshold_eV" if quantity == "threshold_eV" else "source_delta_e_eV"
        assert output not in values
        assert values == {name: value for name, value in original_values.items() if name != output}
        assert output in result.message
        assert assess_reaction_evidence(reaction, evidence).verdict == "pass"
        results.append((result, values))
    assert results[0] == results[1]


@pytest.mark.parametrize("quantity", ["threshold_eV", "delta_e_eV"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf")])
def test_invalid_declaration_is_rejected_at_the_quantity_boundary(
    quantity: str, invalid: float
) -> None:
    _, _, _, record = _case("ionization")
    with pytest.raises(ValueError, match="must be finite"):
        replace(
            record,
            energy_properties=record.energy_properties
            | {quantity: replace(record.energy_properties[quantity], value=invalid)},
        )


@pytest.mark.parametrize("status", ["conflicting", "rejected"])
@pytest.mark.parametrize("scope", ["threshold_eV", "delta_e_eV"])
def test_lifecycle_and_claim_scope_remain_independent_of_other_quantities(
    status: str, scope: str
) -> None:
    reaction, candidates, states, record = _case("ionization")
    another = replace(
        record,
        id="another-declaration",
        energy_properties={
            scope: replace(record.energy_properties[scope], value=20.0, status=status)
        },
    )
    result, values = assess_thermochemistry(
        reaction, candidates, states, ReactionEvidence((record, another)), Conditions()
    )
    expected = "unknown" if status == "conflicting" and scope == "threshold_eV" else "pass"
    assert result.verdict == expected
    assert ("threshold_eV" in values) == (expected == "pass")


@pytest.mark.parametrize("quantity", ["threshold_eV", "deltaE_products_minus_reactants_eV"])
def test_direct_and_saved_declarations_preserve_quantity_dependencies(tmp_path: Path, quantity):
    reaction, candidates, states, record = _case("ionization")
    entry = {
        "id": "first-declaration",
        "reaction": "Ar + e -> Ar+ + 2 e",
        "type": "ionization",
        "status": "reviewed",
        "source": {"citation": "laboratory first declaration"},
        "review_scope": ["channel_assertion", "threshold_eV", "delta_e_eV"],
        "threshold_eV": record.threshold_eV,
        "deltaE_products_minus_reactants_eV": record.delta_e_eV,
    }
    other = {
        **entry,
        "id": "independent-declaration",
        "source": {"citation": "laboratory second declaration"},
        quantity: entry[quantity] + 1,
    }
    source = tmp_path / "snapshot.yaml"
    source.write_text(yamlio.dump({"records": [entry, other]}), encoding="utf-8")
    direct = EvidenceCatalog.load_paths((source,))
    target = reaction_record_candidate(direct.reaction_records[0])
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        yamlio.dump(
            {
                "reaction_records": {
                    target.id: [reaction_record_payload(item) for item in direct.reaction_records]
                }
            }
        ),
        encoding="utf-8",
    )
    staged = EvidenceCatalog.load_paths((overlay,))
    before = assess_thermochemistry(
        target, candidates, states, direct.reaction(target), Conditions()
    )
    after = assess_thermochemistry(
        target, candidates, states, staged.reaction(target), Conditions()
    )
    assert before == after
    assert before[0].verdict == ("unknown" if quantity == "threshold_eV" else "pass")


def test_source_disagreement_preserves_independent_formation_and_gibbs_calculations() -> None:
    atom, molecule = candidate_state({"Ar": 1}, 0), candidate_state({"Ar": 2}, 0)
    reaction = ReactionCandidate(
        "association",
        (Term(atom.id, 2),),
        (Term(molecule.id),),
        "neutral",
        "association",
        "test",
        "test",
        0,
    )
    candidates = CandidateSet(states={state.id: state for state in (atom, molecule)})
    coefficients = (2.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    thermo = Thermo(
        coefficients,
        coefficients,
        200,
        1000,
        2000,
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
    )
    states = {
        state.id: StateEvidence(
            "exact",
            (replace(_state_record(state, enthalpy_formation_eV=value), thermo=thermo),),
        )
        for state, value in ((atom, 0.0), (molecule, 1.0))
    }
    record = ReactionRecord(
        "first",
        reaction.equation_key,
        "neutral",
        "association",
        (atom, molecule),
        energy_properties={
            "threshold_eV": Property(1.0, "eV", tier="reviewed"),
            "delta_e_eV": Property(1.0, "eV", tier="reviewed"),
        },
        tier="reviewed",
    )
    conditions = Conditions(gas_temperature_K=300)
    _, original = assess_thermochemistry(
        reaction, candidates, states, ReactionEvidence((record,)), conditions
    )
    _, disputed = assess_thermochemistry(
        reaction,
        candidates,
        states,
        ReactionEvidence(
            (
                record,
                replace(
                    record,
                    id="another",
                    energy_properties={
                        "threshold_eV": Property(2.0, "eV", tier="reviewed"),
                        "delta_e_eV": Property(2.0, "eV", tier="reviewed"),
                    },
                ),
            )
        ),
        conditions,
    )
    assert "delta_h_eV" in disputed
    assert "delta_g_eV" in disputed
    assert "equilibrium_constant_number_density" in disputed
    assert disputed == {
        name: value
        for name, value in original.items()
        if name not in {"threshold_eV", "source_delta_e_eV"}
    }
