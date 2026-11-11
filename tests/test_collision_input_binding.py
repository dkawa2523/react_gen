"""Collision energy must be scoped to the represented event and beam roles."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen.case import Case, Conditions, Limits
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.export import document, read, write
from reactgen.model import ReactionCandidate, Term
from reactgen.pathway import checked_pathway_query
from reactgen.pipeline import AnalysisResult, analyze
from reactgen.records import Property, ReactionRecord, StateRecord

_F = candidate_state({"F": 1}, 0)
_AR_ION = candidate_state({"Ar": 1}, 1)
_CATALOG = EvidenceCatalog(
    state_records=(
        StateRecord(
            "fluorine test declaration",
            _F,
            properties={
                "mass_amu": Property(19, "u", tier="reviewed"),
                "ionization_energy_eV": Property(10, "eV", tier="reviewed", definition="atomic"),
            },
        ),
        StateRecord(
            "argon test declaration",
            _AR_ION,
            properties={"mass_amu": Property(40, "u", tier="reviewed")},
        ),
    )
)


def _analyze(conditions: Conditions) -> AnalysisResult:
    return analyze(
        Case(
            "beam roles",
            ("F",),
            conditions,
            supplies=("e", "Ar+"),
            limits=Limits(max_depth=1),
        ),
        _CATALOG,
    )


def _channel(saved: dict, partner: str, process: str) -> dict:
    return next(
        row
        for row in saved["reactions"]
        if row["process"] == process
        and {term["species"] for term in row["reactants"]} == {_F.id, partner}
    )


def test_pair_conditions_follow_two_stages_and_keep_other_pairs_out_of_scope(
    tmp_path: Path,
) -> None:
    case = Case.from_document(
        {
            "gases": ["Ar"],
            "supplies": ["e"],
            "limits": {"max_atoms": 1, "max_depth": 2},
            "conditions": {
                "electron_energy_eV": 50,
                "collision_pairs": [
                    {
                        "projectile_state": "e",
                        "target_state": "Ar+",
                        "collision_energy_eV": 28,
                        "collision_energy_frame": "com",
                    },
                    {
                        "projectile_state": "e",
                        "target_state": "Ar",
                        "collision_energy_eV": 17,
                        "collision_energy_frame": "com",
                    },
                    {
                        "projectile_state": "Ar",
                        "target_state": "Ar",
                        "target_at_rest": True,
                        "collision_energy_eV": 20,
                        "collision_energy_frame": "lab",
                    },
                ],
            },
            "reactions": [{"equation": "e + Ar+ -> Ar^2+ + 2 e", "process": "ionization"}],
        }
    )
    catalog = EvidenceCatalog.load(Path(__file__).resolve().parents[1] / "registry")
    write(tmp_path, analyze(case, catalog))
    saved = read(tmp_path, verify_views=True)
    rows = {reaction["id"]: reaction for reaction in saved["reactions"]}
    second_id = case.reactions[0].candidate.id
    checked = checked_pathway_query(saved["states"], saved["reactions"], saved["pathways"])[
        "checked"
    ]
    assert checked["state_layers"]["Ar^2+@ground"] == 2
    first_id = checked["primary_producer"]["Ar+@ground"]
    assert checked["primary_producer"]["Ar^2+@ground"] == second_id
    for identifier, target, threshold, available in (
        (first_id, "Ar@ground", 15.7596119, 17),
        (second_id, "Ar+@ground", 27.62967, 28),
    ):
        reaction = rows[identifier]
        assert reaction["assessments"]["energy"]["verdict"] == "pass"
        margin = reaction["thermochemical_calculations"]["collision_energy_margin_eV"]
        assert margin["value"] == pytest.approx(available - threshold)
        term = next(item for item in margin["inputs"] if "input" in item)
        index = int(term["input"].split("[")[1].split("]")[0])
        pair = saved["input"]["conditions"]["collision_pairs"][index]
        assert pair["target_state"] == term["target_state"] == target
        assert pair["collision_energy_eV"] == term["energy_eV"] == available

    lumped_states = {
        state["id"] for state in saved["states"] if state["state"]["resolution"] == "lumped"
    }
    unresolved = next(
        row
        for row in rows.values()
        if row["process"] == "excitation"
        and {term["species"] for term in row["reactants"]} == {"e", "Ar@ground"}
        and any(term["species"] in lumped_states for term in row["products"])
    )
    assert unresolved["assessments"]["energy"]["verdict"] == "unknown"
    margin = unresolved["thermochemical_calculations"]["collision_energy_margin_eV"]
    assert margin["value"] is None
    assert margin["conditions"]["relative_collision_energy_eV"] == 17
    (entrance,) = margin["inputs"]
    assert (entrance["projectile_state"], entrance["target_state"], entrance["energy_eV"]) == (
        "e",
        "Ar@ground",
        17,
    )

    elastic = next(
        row
        for row in rows.values()
        if row["process"] == "elastic" and row["reactants"] == [{"species": "Ar@ground", "n": 2.0}]
    )
    assert elastic["thermochemical_calculations"]["collision_energy_margin_eV"]["value"] == 10
    outside = [
        row
        for row in rows.values()
        if row["process"] == "elastic"
        and "Ar-@ground" in {term["species"] for term in row["reactants"]}
    ]
    assert outside
    assert all(row["assessments"]["energy"]["verdict"] == "not_applicable" for row in outside)
    assert all(
        not row["thermochemical_calculations"]["collision_energy_margin_eV"]["inputs"]
        for row in outside
    )

    pairs = tuple(
        replace(pair, collision_energy_eV=27) if pair.target_state == "Ar+@ground" else pair
        for pair in reversed(case.conditions.collision_pairs)
    )
    lower = document(
        analyze(replace(case, conditions=replace(case.conditions, collision_pairs=pairs)), catalog)
    )
    verdicts = {item["id"]: item["assessments"]["energy"]["verdict"] for item in lower["reactions"]}
    assert verdicts[first_id] == "pass"
    assert verdicts[second_id] == "fail"
    assert second_id in lower["pathways"]["conditioned"]["excluded"]


def test_pair_conditions_reject_two_energies_for_the_same_unordered_pair() -> None:
    first = {
        "projectile_state": "Ar",
        "target_state": "F",
        "collision_energy_eV": 1,
        "collision_energy_frame": "com",
    }
    second = first | {"projectile_state": "F", "target_state": "Ar", "collision_energy_eV": 2}
    with pytest.raises(ValueError, match="one collision condition per pair"):
        Case.from_document({"gases": ["Ar"], "conditions": {"collision_pairs": [first, second]}})


@pytest.mark.parametrize(
    ("conditions", "quantity"),
    [
        (
            Conditions(electron_energy_eV=20, projectile_state="F", target_at_rest=True),
            "projectile_state",
        ),
        (
            Conditions(electron_energy_eV=20, target_state="e", target_at_rest=True),
            "target_state",
        ),
        (Conditions(electron_energy_eV=20, target_at_rest=False), "target_at_rest"),
    ],
)
def test_invalid_supplied_electron_energy_cannot_pass_even_elastic(
    conditions: Conditions, quantity: str
) -> None:
    saved = document(_analyze(conditions))
    for process in ("elastic", "ionization"):
        row = _channel(saved, "e", process)
        energy = row["assessments"]["energy"]
        assert energy["verdict"] == "unknown"
        assert {(item["responsibility"], item["quantity"]) for item in energy["requirements"]} == {
            ("user_inputs", quantity)
        }
        margin = row["thermochemical_calculations"]["collision_energy_margin_eV"]
        assert margin["value"] is None
        assert margin["conditions"] == {}
        assert margin["inputs"][0]["input"] == "conditions.electron_energy_eV"
        assert margin["inputs"][0]["energy_eV"] == 20

    absent = _channel(document(_analyze(Conditions())), "e", "elastic")
    assert absent["assessments"]["energy"]["verdict"] == "pass"


def test_saved_electron_conversion_uses_actual_condition_key_and_roles(tmp_path: Path) -> None:
    write(tmp_path, _analyze(Conditions(electron_energy_eV=20, target_at_rest=True)))
    saved = read(tmp_path, verify_views=True)
    row = _channel(saved, "e", "ionization")
    assert row["assessments"]["energy"]["verdict"] == "pass"
    margin = row["thermochemical_calculations"]["collision_energy_margin_eV"]
    assert margin["value"] == pytest.approx(20 * 19 / (19 + 0.00054858) - 10)
    term = next(item for item in margin["inputs"] if "input" in item)
    assert term["input"] == "conditions.electron_energy_eV"
    assert (term["projectile_state"], term["target_state"]) == ("e", _F.id)
    assert term["requested_projectile_state"] is None
    assert saved["input"]["conditions"]["electron_energy_eV"] == 20


def test_ion_beam_energy_applies_only_to_an_incident_ion() -> None:
    conditions = Conditions(
        ion_energy_eV=20, projectile_state="Ar+", target_state="F", target_at_rest=True
    )
    row = _channel(document(_analyze(conditions)), _AR_ION.id, "elastic")
    margin = row["thermochemical_calculations"]["collision_energy_margin_eV"]
    assert margin["value"] == pytest.approx(20 * 19 / 59)
    assert margin["inputs"][-1]["input"] == "conditions.ion_energy_eV"

    swapped = Conditions(
        ion_energy_eV=20, projectile_state="F", target_state="Ar+", target_at_rest=True
    )
    row = _channel(document(_analyze(swapped)), _AR_ION.id, "elastic")
    assert row["assessments"]["energy"]["verdict"] == "unknown"
    assert row["assessments"]["energy"]["requirements"][0]["quantity"] == "projectile_state"

    explicit = Conditions(
        collision_energy_eV=20,
        collision_energy_frame="lab",
        ion_energy_eV=20,
        projectile_state="F",
        target_state="Ar+",
        target_at_rest=True,
    )
    row = _channel(document(_analyze(explicit)), _AR_ION.id, "elastic")
    margin = row["thermochemical_calculations"]["collision_energy_margin_eV"]
    assert margin["value"] == pytest.approx(20 * 40 / 59)
    assert margin["inputs"][-1]["input"] == "conditions.collision_energy_eV"


@pytest.mark.parametrize(
    ("phase", "verdict"), [("solid", "not_applicable"), ("unknown", "unknown")]
)
def test_external_channel_requires_gas_participant_phases(phase: str, verdict: str) -> None:
    gas = candidate_state({"Ar": 1}, 0)
    product = candidate_state({"Ar": 1}, 0, phase=phase)
    reaction = ReactionCandidate(
        "phase-change",
        (Term(gas.id), Term(_F.id)),
        (Term(product.id), Term(_F.id)),
        "neutral",
        "phase_change",
        "external",
        "test",
        0,
    )
    source = ReactionRecord(
        "external phase-change test declaration",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (gas, product, _F),
    )
    incoming = reaction.products
    elastic = ReactionCandidate(
        "phase-elastic", incoming, incoming, "neutral", "elastic", "external", "test", 0
    )
    collision = ReactionRecord(
        "external elastic test declaration",
        elastic.equation_key,
        elastic.family,
        elastic.process,
        (product, _F),
    )
    case = Case(
        "phase-change",
        ("Ar", "F"),
        Conditions(collision_energy_eV=1, collision_energy_frame="com"),
        limits=Limits(max_depth=2),
    )
    saved = document(analyze(case, EvidenceCatalog(reaction_records=(source, collision))))
    row = _channel(saved, product.id, elastic.process)
    assessments = row["assessments"]
    assert assessments["conservation"]["verdict"] == "pass"
    assert assessments["energy"]["verdict"] == verdict
    assert "collision_energy_margin_eV" not in row["thermochemical_calculations"]
    if phase == "solid":
        assert assessments["consistency"]["verdict"] == "fail"
        assert assessments["energy"]["requirements"] == []
    else:
        assert {
            (item["responsibility"], item["target"], item["quantity"])
            for item in assessments["energy"]["requirements"]
        } == {("identity", product.id, "phase")}
