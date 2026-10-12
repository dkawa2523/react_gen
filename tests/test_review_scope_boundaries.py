"""A reviewed scientific claim cannot approve another quantity or proposition."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import export, ingest, yamlio
from reactgen.assessment import assess_reaction_evidence, assess_thermochemistry
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.pipeline import analyze
from reactgen.records import Property, ReactionRecord


def snapshot(path: Path, scopes: list[str] | None) -> Path:
    record = {
        "id": "numerical-record",
        "reaction": "e + Ar -> e + e + Ar+",
        "type": "ionization",
        "status": "reviewed",
        "form": "constant",
        "unit": "m3/s",
        "parameters": {"value": 1e-15},
        "independent_variable": "gas_temperature",
        "validity": {"quantity": "gas_temperature", "minimum": 300, "maximum": 300, "unit": "K"},
        "threshold_eV": 17.0,
        "deltaE_products_minus_reactants_eV": 16.0,
    }
    if scopes is not None:
        record["review_scope"] = scopes
    path.write_text(yamlio.dump({"snapshot_version": 1, "records": [record]}), encoding="utf-8")
    return path


def selected_reaction(analysis):
    return next(
        reaction
        for reaction in analysis.candidates.reactions.values()
        if reaction.process == "ionization"
        and any(term.species == "Ar+@ground" for term in reaction.products)
        and any(term.species == "Ar@ground" for term in reaction.reactants)
    )


@pytest.mark.parametrize(
    "scopes",
    [None, [], ["rate_coefficient"], ["channel_assertion"], ["threshold_eV"], ["delta_e_eV"]],
)
def test_snapshot_review_qualifies_only_its_declared_claims(tmp_path: Path, scopes) -> None:
    source = snapshot(tmp_path / "snapshot.yaml", scopes)
    case = Case("scope", ("Ar",), conditions=Conditions(gas_temperature_K=300))
    analysis = analyze(case, EvidenceCatalog.load_paths((source,)))
    reaction = selected_reaction(analysis)
    assessments = analysis.evaluation.reaction_assessments[reaction.id]
    values = analysis.evaluation.thermochemistry.get(reaction.id, {})
    numerical = not scopes or "rate_coefficient" in scopes
    assert assessments["reaction_evidence"].verdict == (
        "pass" if scopes and "channel_assertion" in scopes else "unknown"
    )
    assert analysis.evaluation.data_use[reaction.id].status == (
        "coefficient" if numerical else "unavailable"
    )
    assert ("threshold_eV" in values) == bool(scopes and "threshold_eV" in scopes)
    assert ("source_delta_e_eV" in values) == bool(scopes and "delta_e_eV" in scopes)


def test_numerical_snapshot_and_ingest_agree_without_recreating_channel_review(tmp_path) -> None:
    source = snapshot(tmp_path / "snapshot.yaml", ["rate_coefficient"])
    case = Case("scope", ("Ar",), conditions=Conditions(gas_temperature_K=300))
    direct = analyze(case, EvidenceCatalog.load_paths((source,)))
    bundle, overlay = tmp_path / "bundle", tmp_path / "overlay.yaml"
    export.write(bundle, direct)
    assert ingest.ingest(source, bundle, overlay).accepted == 1
    staged = analyze(case, EvidenceCatalog.load_paths((overlay,)))
    reaction = selected_reaction(direct)
    for analysis in (direct, staged):
        judgments = analysis.evaluation.reaction_assessments[reaction.id]
        assert judgments["reaction_evidence"].verdict == "unknown"
        values = analysis.evaluation.thermochemistry.get(reaction.id, {})
        assert "threshold_eV" not in values
        assert "source_delta_e_eV" not in values
        assert analysis.evaluation.data_use[reaction.id].value == 1e-15


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_rejected_or_conflicting_source_cannot_be_approved_by_a_reviewed_tier(tmp_path, status):
    source = snapshot(tmp_path / "snapshot.yaml", ["channel_assertion", "threshold_eV"])
    document = yamlio.load(source.read_text(encoding="utf-8"))
    document["records"][0].update(status=status, tier="reviewed")
    source.write_text(yamlio.dump(document), encoding="utf-8")
    case = Case("scope", ("Ar",), conditions=Conditions(gas_temperature_K=300))
    analysis = analyze(case, EvidenceCatalog.load_paths((source,)))
    reaction = selected_reaction(analysis)
    assert (
        analysis.evaluation.reaction_assessments[reaction.id]["reaction_evidence"].verdict
        == "unknown"
    )
    assert "threshold_eV" not in analysis.evaluation.thermochemistry.get(reaction.id, {})
    assert analysis.evaluation.data_use[reaction.id].status == "unavailable"


def channel_declaration(reaction) -> ReactionRecord:
    return ReactionRecord(
        "channel-record",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        energy_properties={"threshold_eV": Property(16.0, "eV", tier="reviewed")},
        status="reviewed",
        tier="reviewed",
        review_scope=("channel_assertion", "threshold_eV"),
    )


@pytest.mark.parametrize(
    ("scopes", "verdict"),
    [
        (("channel_assertion",), "unknown"),
        (("threshold_eV",), "pass"),
        (("rate_coefficient",), "pass"),
    ],
)
def test_a_stated_conflict_affects_only_its_scoped_claim(scopes, verdict) -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = channel_declaration(reaction)
    conflicting = replace(
        reviewed,
        id="another-source",
        status="conflicting",
        review_scope=scopes,
        energy_properties={
            "threshold_eV": replace(
                reviewed.energy_properties["threshold_eV"], status="conflicting"
            )
        }
        if "threshold_eV" in scopes
        else {},
    )
    for ordered in ((reviewed, conflicting), (conflicting, reviewed)):
        evidence = ReactionEvidence(ordered)
        assert assess_reaction_evidence(reaction, evidence).verdict == verdict
        _, values = assess_thermochemistry(
            reaction, analysis.candidates, {}, evidence, Conditions()
        )
        assert ("threshold_eV" not in values) == (scopes == ("threshold_eV",))


@pytest.mark.parametrize("same_id", [False, True])
def test_another_energy_quantity_does_not_change_the_channel_assertion(same_id) -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = channel_declaration(reaction)
    changed = replace(
        reviewed,
        id=reviewed.id if same_id else "independent-source",
        energy_properties={"threshold_eV": Property(17.0, "eV", tier="reviewed")},
    )
    for ordered in ((reviewed, changed), (changed, reviewed)):
        result = assess_reaction_evidence(reaction, ReactionEvidence(ordered))
        assert result.verdict == "pass"


def test_reacquisition_context_alone_is_not_a_channel_record_identity_conflict() -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = replace(
        channel_declaration(reaction), source_declaration={"acquisition": {"retrieved_at": "A"}}
    )
    reacquired = replace(reviewed, source_declaration={"acquisition": {"retrieved_at": "B"}})
    assert (
        assess_reaction_evidence(reaction, ReactionEvidence((reviewed, reacquired))).verdict
        == "pass"
    )


@pytest.mark.parametrize("same_id", [False, True])
def test_a_conflict_for_another_process_is_relevant_only_when_its_record_id_collides(
    same_id,
) -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = channel_declaration(reaction)
    other_process = replace(
        reviewed,
        id=reviewed.id if same_id else "other-process",
        process="dissociation",
        status="conflicting",
        review_scope=("channel_assertion",),
    )
    evidence = ReactionEvidence((reviewed,), (other_process,))
    assert assess_reaction_evidence(reaction, evidence).verdict == (
        "unknown" if same_id else "pass"
    )


@pytest.mark.parametrize("changed", ["threshold_eV", "delta_e_eV"])
def test_same_record_other_scalar_conflict_does_not_discard_an_independent_energy_value(
    changed,
) -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = replace(
        channel_declaration(reaction),
        energy_properties=channel_declaration(reaction).energy_properties
        | {"delta_e_eV": Property(10.0, "eV", tier="reviewed")},
        review_scope=("channel_assertion", "threshold_eV", "delta_e_eV"),
        source_declaration={
            "threshold_eV": 16.0,
            "deltaE_products_minus_reactants_eV": 10.0,
        },
    )
    declaration = dict(reviewed.source_declaration)
    declaration[
        "threshold_eV" if changed == "threshold_eV" else "deltaE_products_minus_reactants_eV"
    ] = 20.0
    another = replace(
        reviewed,
        energy_properties=reviewed.energy_properties
        | {changed: replace(reviewed.energy_properties[changed], value=20.0)},
        source_declaration=declaration,
    )
    for ordered in ((reviewed, another), (another, reviewed)):
        evidence = ReactionEvidence(ordered)
        assert assess_reaction_evidence(reaction, evidence).verdict == "pass"
        _, values = assess_thermochemistry(
            reaction, analysis.candidates, {}, evidence, Conditions()
        )
        changed_output = "threshold_eV" if changed == "threshold_eV" else "source_delta_e_eV"
        retained_output = "source_delta_e_eV" if changed == "threshold_eV" else "threshold_eV"
        assert changed_output not in values
        assert retained_output in values


def test_channel_claim_projection_keeps_unknown_scientific_conditions() -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = replace(
        channel_declaration(reaction),
        source_declaration={"conditions": {"unmodelled_distribution": "A"}},
    )
    another = replace(reviewed, source_declaration={"conditions": {"unmodelled_distribution": "B"}})
    for ordered in ((reviewed, another), (another, reviewed)):
        assert assess_reaction_evidence(reaction, ReactionEvidence(ordered)).verdict == "unknown"


def test_channel_claim_projection_does_not_compare_coefficient_parameters() -> None:
    analysis = analyze(Case("scope", ("Ar",)), EvidenceCatalog())
    reaction = selected_reaction(analysis)
    reviewed = replace(
        channel_declaration(reaction),
        source_declaration={"form": "constant", "parameters": {"value": 1.0}, "unit": "m3/s"},
    )
    another = replace(
        reviewed,
        source_declaration={"form": "constant", "parameters": {"value": 2.0}, "unit": "m3/s"},
    )
    assert (
        assess_reaction_evidence(reaction, ReactionEvidence((reviewed, another))).verdict == "pass"
    )
