"""Read-only evidence matching and the five four-valued assessments."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from reactgen.assessment import assess_consistency, assess_kinetics, assess_reaction_evidence
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.generate import candidates
from reactgen.model import CandidateSet, ReactionCandidate, Term, reaction_id
from reactgen.pipeline import run
from reactgen.records import normalized_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


def _argon_elastic() -> ReactionCandidate:
    reaction = ReactionCandidate(
        id="",
        reactants=(Term("e"), Term("Ar@ground")),
        products=(Term("e"), Term("Ar@ground")),
        family="electron",
        process="elastic",
        origin="mechanical",
        generation_rule="test",
        depth=1,
    )
    return ReactionCandidate(**{**reaction.__dict__, "id": reaction_id(reaction.key)})


def test_state_evidence_distinguishes_exact_ambiguous_and_none() -> None:
    generated = candidates(("Ar", "O2"))
    argon = generated.states["Ar@ground"]
    oxygen = generated.states["O2@ground"]
    exact = EvidenceCatalog.load(FIXTURE)
    assert exact.state(argon).match == "exact"
    assert exact.state(oxygen).match == "none"

    argon_record = next(record for record in exact.state_records if record.id == "Ar")
    duplicate = replace(argon_record, id="Ar_duplicate", existence="unbound")
    ambiguous = EvidenceCatalog(
        state_records=(*exact.state_records, duplicate),
        reaction_records=exact.reaction_records,
        materials=exact.materials,
        fingerprint="test",
    )
    assert ambiguous.state(argon).match == "ambiguous"


def test_overlay_fills_registry_gaps_without_creating_a_second_state(tmp_path: Path) -> None:
    generated = candidates(("Ar",))
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        yaml.safe_dump(
            {
                "properties": {
                    "Ar@ground": {
                        "enthalpy_formation_eV": {
                            "value": 0.0,
                            "unit": "eV",
                            "source": "reviewed overlay",
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with_overlay = EvidenceCatalog.load(FIXTURE, overlay)
    evidence = with_overlay.state(generated.states["Ar@ground"])
    assert evidence.match == "exact"
    assert evidence.preferred is not None
    assert evidence.preferred.value("enthalpy_formation_eV") == 0.0


def test_attested_only_channels_are_added_without_changing_mechanical_keys() -> None:
    mechanical = candidates(("F2",))
    combined = EvidenceCatalog.load(FIXTURE).with_attested(mechanical)
    assert {reaction.key for reaction in mechanical.reactions.values()} <= {
        reaction.key for reaction in combined.reactions.values()
    }
    assert any(reaction.origin == "attested_only" for reaction in combined.reactions.values())
    assert all(state.origin == "mechanical" for state in mechanical.states.values())


def test_evidence_fingerprint_depends_on_content_not_checkout_path(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    shutil.copytree(FIXTURE, first)
    shutil.copytree(FIXTURE, second)
    assert EvidenceCatalog.load(first).fingerprint == EvidenceCatalog.load(second).fingerprint


def test_total_process_does_not_poison_exact_channel_evidence(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text(
        yaml.safe_dump(
            {
                "kind": "cross_section",
                "source": {"source_id": "reviewed-test"},
                "records": [
                    {
                        "id": "channel",
                        "reaction": "e + Ar -> e + Ar",
                        "family": "electron",
                        "type": "elastic",
                        "channel_scope": "product_resolved",
                        "status": "reviewed",
                    },
                    {
                        "id": "total",
                        "reaction": "e + Ar -> e + Ar",
                        "family": "electron",
                        "type": "elastic",
                        "channel_scope": "total",
                        "status": "reviewed",
                    },
                    {
                        "id": "different-process",
                        "reaction": "e + Ar -> e + Ar",
                        "family": "electron",
                        "type": "excitation",
                        "channel_scope": "product_resolved",
                        "status": "reviewed",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    evidence = EvidenceCatalog.load(None, known=(snapshot,)).reaction(_argon_elastic())
    assert len(evidence.exact_records) == 1
    assert len(evidence.total_records) == 1
    assert len(evidence.related_records) == 1
    assert assess_reaction_evidence(_argon_elastic(), evidence).verdict == "pass"


def test_missing_data_is_unknown_and_bad_scope_or_range_fails(tmp_path: Path) -> None:
    reaction = _argon_elastic()
    unknown, _ = assess_kinetics(reaction, ReactionEvidence(), Conditions())
    assert unknown.verdict == "unknown"

    asset = tmp_path / "table.csv"
    asset.write_text("energy,cross_section\n1,1e-20\n100,2e-20\n", encoding="utf-8")
    total_data = {
        "id": "total",
        "kind": "cross_section",
        "form": "table",
        "unit": "m2",
        "independent_variable": "electron_energy",
        "observable": "elastic",
        "channel_scope": "total",
        "asset": asset.name,
        "status": "reviewed",
        "validity": {
            "quantity": "collision_energy",
            "minimum": 1.0,
            "maximum": 100.0,
            "unit": "eV",
        },
    }
    total = ReactionEvidence(overlay_datasets=(normalized_dataset(total_data, base=tmp_path),))
    invalid, _ = assess_kinetics(reaction, total, Conditions())
    assert invalid.verdict == "fail"

    product = ReactionEvidence(
        overlay_datasets=(
            normalized_dataset(
                total_data | {"id": "product", "channel_scope": "product_resolved"},
                base=tmp_path,
            ),
        )
    )
    usable, capabilities = assess_kinetics(reaction, product, Conditions())
    assert usable.verdict == "pass"
    assert capabilities.cross_section_ready

    wrong_observable = ReactionEvidence(
        overlay_datasets=(
            normalized_dataset(
                total_data
                | {
                    "id": "wrong-observable",
                    "channel_scope": "product_resolved",
                    "observable": "charge_exchange",
                },
                base=tmp_path,
            ),
        )
    )
    invalid_observable, _ = assess_kinetics(reaction, wrong_observable, Conditions())
    assert invalid_observable.verdict == "fail"
    assert not capabilities.direct_rate_ready
    assert capabilities.required_transforms == ("eedf_integration",)

    missing_asset = ReactionEvidence(
        overlay_datasets=(
            normalized_dataset(
                total_data
                | {
                    "id": "missing-table",
                    "asset": "missing.csv",
                    "channel_scope": "product_resolved",
                },
                base=tmp_path,
            ),
        )
    )
    unavailable, _ = assess_kinetics(reaction, missing_asset, Conditions())
    assert unavailable.verdict == "unknown"

    out_of_range = ReactionEvidence(
        overlay_datasets=(
            normalized_dataset(
                {
                    "id": "cold",
                    "kind": "rate_coefficient",
                    "form": "constant",
                    "unit": "m3/s",
                    "independent_variable": "gas_temperature",
                    "parameters": {"value": 1.0e-15},
                    "status": "reviewed",
                    "validity": {
                        "quantity": "gas_temperature",
                        "minimum": 10.0,
                        "maximum": 100.0,
                        "unit": "K",
                    },
                },
            ),
        )
    )
    invalid, _ = assess_kinetics(
        reaction,
        out_of_range,
        Conditions(gas_temperature_K=300.0),
    )
    assert invalid.verdict == "fail"

    wrong_order = ReactionEvidence(
        overlay_datasets=(
            normalized_dataset(
                {
                    "id": "wrong-order",
                    "kind": "rate_coefficient",
                    "form": "constant",
                    "unit": "s-1",
                    "parameters": {"value": 1.0},
                    "status": "reviewed",
                }
            ),
        )
    )
    invalid, _ = assess_kinetics(reaction, wrong_order, Conditions())
    assert invalid.verdict == "fail"


def test_conflicting_preferred_constants_are_unknown() -> None:
    reaction = _argon_elastic()
    records = tuple(
        normalized_dataset(
            {
                "id": f"rate_{value}",
                "kind": "rate_coefficient",
                "form": "constant",
                "unit": "m3/s",
                "independent_variable": None,
                "parameters": {"value": value},
                "preferred": True,
                "status": "reviewed",
            }
        )
        for value in (1.0e-15, 2.0e-15)
    )
    assessed, _ = assess_kinetics(
        reaction,
        ReactionEvidence(overlay_datasets=records),
        Conditions(),
    )
    assert assessed.verdict == "unknown"


def test_structural_failure_is_fail_not_unknown() -> None:
    generated = candidates(("Ar",))
    broken = ReactionCandidate(
        id="broken",
        reactants=(Term("Ar@ground"),),
        products=(Term("Ar+@ground"),),
        family="neutral",
        process="impossible",
        origin="mechanical",
        generation_rule="test",
        depth=1,
    )
    network = CandidateSet(states=generated.states, reactions={"broken": broken})
    assert assess_consistency(broken, network).verdict == "fail"


def test_negative_or_explicitly_unbound_affinity_rejects_parent_anions() -> None:
    catalog = EvidenceCatalog.load(Path("registry"))
    argon = run(Case("argon", ("Ar",)), catalog)
    carbon_tetrafluoride = run(Case("cf4", ("CF4",)), catalog)
    assert argon.evaluation.state_assessments["Ar-@ground"]["state"].verdict == "fail"
    assert (
        carbon_tetrafluoride.evaluation.state_assessments["CF4-@ground"]["state"].verdict == "fail"
    )


def test_mixed_argon_4s_evidence_is_not_misassigned_to_a_lifetime_submanifold() -> None:
    result = run(Case("argon", ("Ar",)), EvidenceCatalog.load(Path("registry")))
    assert result.evaluation.state_evidence["Ar@4s"].match == "exact"
    assert result.evaluation.state_evidence["Ar@metastable"].match == "compatible"
    assert result.evaluation.state_evidence["Ar@resonant"].match == "compatible"
    assert result.evaluation.state_assessments["Ar@4s"]["state"].verdict == "pass"
    assert result.evaluation.state_assessments["Ar@metastable"]["state"].verdict == "unknown"
    assert result.evaluation.state_assessments["Ar@resonant"]["state"].verdict == "unknown"


@pytest.mark.parametrize("value", [-0.5, 0.5])
def test_unreviewed_electron_affinity_does_not_decide_anion_existence(
    tmp_path: Path,
    value: float,
) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        yaml.safe_dump(
            {
                "properties": {
                    "Ar@ground": {
                        "electron_affinity_eV": {
                            "value": value,
                            "unit": "eV",
                            "evidence_tier": "imported",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = run(Case("argon", ("Ar",)), EvidenceCatalog.load(None, overlay=overlay))
    assert result.evaluation.state_assessments["Ar-@ground"]["state"].verdict == "unknown"


def test_penning_energy_and_electron_reverse_rate_are_not_assumed() -> None:
    result = run(Case("argon", ("Ar",)), EvidenceCatalog.load(Path("registry")))
    penning = next(
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.process == "penning_ionization"
    )
    assert result.evaluation.reaction_assessments[penning.id]["thermochemistry"].verdict == "fail"
    assert result.evaluation.thermochemistry[penning.id]["penning_available_energy_eV"] < 0
    electron_thermo = [
        result.evaluation.thermo_capabilities[reaction.id]
        for reaction in result.candidates.reactions.values()
        if reaction.family == "electron"
    ]
    assert electron_thermo
    assert all(not item.equilibrium_constant_ready for item in electron_thermo)
    assert all(not item.reverse_rate_ready for item in electron_thermo)


def test_reverse_rate_is_limited_to_thermal_reversible_channels() -> None:
    result = run(
        Case("cf4", ("CF4",), conditions=Conditions(gas_temperature_K=300.0)),
        EvidenceCatalog.load(Path("registry")),
    )
    ready = {
        reaction.process
        for reaction in result.candidates.reactions.values()
        if result.evaluation.thermo_capabilities[reaction.id].reverse_rate_ready
    }
    assert "reactive_scattering" in ready
    assert "mutual_neutralization" not in ready
    assert ready <= {
        "charge_exchange",
        "resonant_charge_exchange",
        "ligand_transfer",
        "radical_abstraction",
        "reactive_scattering",
    }


def test_table_values_are_checked_not_only_the_asset_reference(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("energy,cross_section\n2,1e-20\n1,-1e-20\n", encoding="utf-8")
    dataset = normalized_dataset(
        {
            "id": "bad-table",
            "kind": "cross_section",
            "form": "table",
            "unit": "m2",
            "independent_variable": "electron_energy",
            "asset": bad.name,
            "status": "reviewed",
        },
        base=tmp_path,
    )
    assessed, capabilities = assess_kinetics(
        _argon_elastic(),
        ReactionEvidence(overlay_datasets=(dataset,)),
        Conditions(),
    )
    assert assessed.verdict == "fail"
    assert not capabilities.cross_section_ready
