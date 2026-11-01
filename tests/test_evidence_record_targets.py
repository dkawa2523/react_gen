"""Scientific record identity remains tied to its physical subject across boundaries."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.assessment import evaluate
from reactgen.case import Case, Conditions
from reactgen.chemistry import parse_equation
from reactgen.evidence import EvidenceCatalog, reaction_record_candidate
from reactgen.pipeline import analyze
from reactgen.records import ReactionRecord, dataset_payload, normalized_dataset
from reactgen.selection import DataSelection


def write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(value), encoding="utf-8")
    return path


def rate(**changes):
    return {
        "id": "measurement",
        "kind": "rate_coefficient",
        "form": "constant",
        "unit": "m3/s",
        "reaction_order": 2,
        "parameters": {"value": 1e-15},
        "independent_variable": "gas_temperature",
        "validity": {"quantity": "gas_temperature", "minimum": 300, "maximum": 500, "unit": "K"},
        "status": "reviewed",
        **changes,
    }


def elastic_targets():
    result = analyze(Case("mixture", ("Ar", "Ne")), EvidenceCatalog())
    return {
        gas: next(
            reaction
            for reaction in result.candidates.reactions.values()
            if reaction.process == "elastic"
            and {term.species for term in reaction.reactants} == {"e", f"{gas}@ground"}
        )
        for gas in ("Ar", "Ne")
    }


@pytest.mark.parametrize("native", ["record", "source", "header"])
def test_reaction_native_id_is_not_reused_as_a_participant_state_id(tmp_path, native):
    record = {"reaction": "e + Ar -> e + Ar", "type": "elastic", "status": "reviewed"}
    source = {"provider": "laboratory"}
    if native == "record":
        record["record_id"] = "channel-1"
    elif native == "source":
        record["source"] = {"record_id": "channel-1"}
    else:
        source["record_id"] = "channel-1"
    path = write(tmp_path / "snapshot.yaml", {"source": source, "records": [record]})
    catalog = EvidenceCatalog.load_paths((path,))
    assert {state.id for state in catalog.state_records} == {"e", "Ar@ground"}
    for state in catalog.state_records:
        assert state.existence == "unknown"
        assert not state.reviewed
        assert state.provenance.record_id is None
        assert state.source_declaration["derived_from_reaction"] == catalog.reaction_records[0].id
    assert catalog.reaction_records[0].provenance.record_id == "channel-1" or native == "record"


@pytest.mark.parametrize("reverse", [False, True])
def test_one_numerical_id_cannot_be_bound_to_two_channels_but_same_target_conflicts_remain(
    tmp_path, reverse
):
    targets = elastic_targets()
    groups = [(targets[gas].id, [rate()]) for gas in ("Ar", "Ne")]
    if reverse:
        groups.reverse()
    path = write(tmp_path / "overlay.yaml", {"datasets": dict(groups)})
    with pytest.raises(ValueError, match="different physical targets"):
        EvidenceCatalog.load_paths((path,))
    path = write(
        path,
        {"datasets": {targets["Ar"].id: [rate(), rate(parameters={"value": 2e-15})]}},
    )
    result = analyze(
        Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=350)),
        EvidenceCatalog.load_paths((path,)),
    )
    assert result.evaluation.data_use[targets["Ar"].id].status == "conflict"


@pytest.mark.parametrize(
    "assertion",
    [
        {"reaction": "e + Ar -> e + Ar"},
        {"type": "ionization"},
        {"family": "surface"},
        {"third_body": "M"},
        {"surface": "Si"},
        {"stabilization": "radiative"},
    ],
)
def test_explicit_numerical_subject_must_agree_with_its_enclosing_channel(tmp_path, assertion):
    target = elastic_targets()["Ne"]
    path = write(tmp_path / "overlay.yaml", {"datasets": {target.id: [rate(**assertion)]}})
    with pytest.raises(ValueError, match="physical reaction target"):
        analyze(Case("neon", ("Ne",)), EvidenceCatalog.load_paths((path,)))


def test_numerical_subject_survives_ingest_adopt_and_saved_result_validation(tmp_path):
    targets = elastic_targets()
    case = Case("mixture", ("Ar", "Ne"), conditions=Conditions(gas_temperature_K=350))
    bundle, overlay = tmp_path / "result", tmp_path / "overlay.yaml"
    export.write(bundle, analyze(case, EvidenceCatalog()))
    snapshot = write(
        tmp_path / "snapshot.yaml",
        {"records": [rate(reaction="e + Ar -> e + Ar", type="elastic")]},
    )
    assert ingest.ingest(snapshot, bundle, overlay).accepted == 1
    snapshot = write(snapshot, {"records": [rate(reaction="e + Ne -> e + Ne", type="elastic")]})
    report = ingest.ingest(snapshot, bundle, overlay)
    assert report.accepted == 0
    assert "different physical targets" in report.review[0]["reason"]
    catalog = EvidenceCatalog.load_paths((overlay,))
    dataset = catalog.overlay_datasets[targets["Ar"].id][0]
    assert dataset.reaction_target == targets["Ar"].id
    assert dataset.declared_target == {"reaction": "e + Ar -> e + Ar", "type": "elastic"}
    result = analyze(case, catalog)
    export.write(bundle, result)
    document = export.read(bundle, verify_views=True)
    argon = next(row for row in document["reactions"] if row["id"] == targets["Ar"].id)
    argon["evidence"]["overlay_datasets"][0]["reaction_target"] = targets["Ne"].id
    with pytest.raises(ValueError, match="physical target"):
        export.validate(document)

    registry = tmp_path / "registry"
    for gas in ("Ar", "Ne"):
        write(
            registry / "species" / f"{gas}.yaml",
            {"id": gas, "phase": "gas", "composition": {gas: 1}},
        )
        write(
            registry / "reactions" / "electron" / f"{gas}.yaml",
            {
                "pair": {"family": "electron", "projectile": "e", "target": gas},
                "channels": [
                    {
                        "id": f"elastic-{gas}",
                        "type": "elastic",
                        "products": [{"species": "e"}, {"species": gas}],
                    }
                ],
            },
        )
    adopted = adopt.adopt(overlay, registry)
    assert "measurement" in adopted.written[targets["Ar"].id]
    repeated = adopt.adopt(overlay, registry)
    assert not repeated.written
    assert "measurement" in repeated.kept[targets["Ar"].id]
    wrong = write(tmp_path / "wrong.yaml", {"datasets": {targets["Ne"].id: [rate()]}})
    before = {path: path.read_bytes() for path in registry.rglob("*.yaml")}
    with pytest.raises(ValueError, match="different physical targets"):
        adopt.adopt(wrong, registry)
    assert {path: path.read_bytes() for path in before} == before


def test_source_declaration_is_not_reinterpreted_as_an_explicit_target(tmp_path):
    target = elastic_targets()["Ne"]
    record = rate(source_declaration={"reaction": "free text from an unrelated source section"})
    dataset = normalized_dataset(record)
    assert not dataset.declared_target
    path = write(tmp_path / "overlay.yaml", {"datasets": {target.id: [dataset_payload(dataset)]}})
    document = export.document(analyze(Case("neon", ("Ne",)), EvidenceCatalog.load_paths((path,))))
    selected = next(row for row in document["reactions"] if row["id"] == target.id)
    assert (
        selected["evidence"]["overlay_datasets"][0]["source_declaration"]
        == record["source_declaration"]
    )


def test_saved_numerical_ids_cannot_move_between_channels(tmp_path):
    targets = elastic_targets()
    path = write(
        tmp_path / "overlay.yaml",
        {"datasets": {target.id: [rate(id=gas)] for gas, target in targets.items()}},
    )
    result = analyze(Case("mixture", ("Ar", "Ne")), EvidenceCatalog.load_paths((path,)))
    document = export.document(result)
    neon = next(row for row in document["reactions"] if row["id"] == targets["Ne"].id)
    neon["evidence"]["overlay_datasets"][0]["id"] = "Ar"
    with pytest.raises(ValueError, match="different physical targets"):
        export.validate(document)


def test_ingest_checks_existing_overlay_target_assertions_before_writing(tmp_path):
    targets = elastic_targets()
    bundle, overlay = tmp_path / "result", tmp_path / "overlay.yaml"
    export.write(bundle, analyze(Case("mixture", ("Ar", "Ne")), EvidenceCatalog()))
    write(
        overlay,
        {"datasets": {targets["Ne"].id: [rate(reaction="e + Ar -> e + Ar")]}},
    )
    source = write(tmp_path / "snapshot.yaml", {"records": []})
    before = overlay.read_bytes()
    with pytest.raises(ValueError, match="physical reaction target"):
        ingest.ingest(source, bundle, overlay)
    assert overlay.read_bytes() == before


def test_saved_channel_evidence_cannot_retarget_its_quantities_or_normalize_invalid_terms(tmp_path):
    targets = elastic_targets()
    path = write(
        tmp_path / "snapshot.yaml",
        {
            "records": [
                rate(id=gas, reaction=f"e + {gas} -> e + {gas}", type="elastic")
                for gas in ("Ar", "Ne")
            ]
        },
    )
    result = analyze(Case("mixture", ("Ar", "Ne")), EvidenceCatalog.load_paths((path,)))
    document = export.document(result)
    argon = next(row for row in document["reactions"] if row["id"] == targets["Ar"].id)
    neon = next(row for row in document["reactions"] if row["id"] == targets["Ne"].id)
    neon["evidence"]["records"][0] = argon["evidence"]["records"][0]
    with pytest.raises(ValueError, match="physical target"):
        export.validate(document)
    document = export.document(result)
    argon = next(row for row in document["reactions"] if row["id"] == targets["Ar"].id)
    argon["evidence"]["records"][0]["equation_key"][3] = [
        ["e", 1],
        ["Ar@ground", -1],
        ["Ar@ground", 2],
    ]
    with pytest.raises(ValueError, match="stoichiometric"):
        export.validate(document)


def test_record_selection_does_not_borrow_another_sources_missing_property(tmp_path):
    reference = {"temperature_K": 298.15, "basis": "standard_elements", "standard_pressure_Pa": 1e5}

    def enthalpy(value):
        return {"value": value, "unit": "eV", "tier": "reviewed", "formation_reference": reference}

    root = tmp_path / "registry"
    write(
        root / "species" / "F.yaml",
        {
            "id": "F",
            "phase": "gas",
            "composition": {"F": 1},
            "properties": {"enthalpy_formation_eV": enthalpy(1)},
        },
    )
    original = {"record_id": "original-F2", "properties": {"enthalpy_formation_eV": enthalpy(None)}}
    write(
        root / "species" / "F2.yaml",
        {"id": "F2", "phase": "gas", "composition": {"F": 2}, "records": [original]},
    )
    overlay = write(
        tmp_path / "overlay.yaml",
        {
            "state_records": {
                "F2@ground": [
                    {
                        "record_id": "alternative-F2",
                        "phase": "gas",
                        "properties": {"enthalpy_formation_eV": enthalpy(3)},
                    }
                ]
            }
        },
    )
    selected = DataSelection.from_document(
        {"targets": {"F2@ground": {"enthalpy_formation_eV": {"record": "original-F2"}}}}
    )
    catalog = EvidenceCatalog.load_paths((root, overlay))
    retained = next(record for record in catalog.state_records if record.record_id == "original-F2")
    assert retained.value("enthalpy_formation_eV") is None
    case = Case("fluorine", ("F2",))
    for selection, expected in ((selected, None), (DataSelection(), -1)):
        result = analyze(replace(case, data_selection=selection), catalog)
        dissociation = next(
            reaction
            for reaction in result.candidates.reactions.values()
            if reaction.process == "dissociation"
        )
        calculation = result.evaluation.thermochemical_calculations[dissociation.id]["delta_h_eV"]
        assert calculation.value == expected


@pytest.mark.parametrize(
    ("equation", "process", "family"),
    [
        ("e + Ar -> e + Ar", "elastic", "electron"),
        ("Ar+ + Ne -> Ar + Ne+", "charge_exchange", "ion"),
    ],
)
def test_quantity_target_does_not_depend_on_optional_participant_record_copies(
    equation, process, family
):
    parsed = parse_equation(equation)
    assert parsed is not None
    record = ReactionRecord(
        "source", parsed[0], None, process, (), datasets=(normalized_dataset(rate()),)
    )
    target = reaction_record_candidate(record)
    assert target.family == family
    catalog = EvidenceCatalog(reaction_records=(record,))
    assert catalog.reaction_records[0].datasets[0].reaction_target == target.id
    if family == "electron":
        result = analyze(
            Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=350)), catalog
        )
        assert result.evaluation.data_use[target.id].value == 1e-15
        export.document(result)


def test_candidate_reference_aliases_are_resolved_before_physical_dataset_binding():
    targets = elastic_targets()
    candidates = analyze(Case("mixture", ("Ar", "Ne")), EvidenceCatalog()).candidates
    aliases = {
        gas: replace(target, id=f"{gas} candidate reference") for gas, target in targets.items()
    }
    dataset = normalized_dataset(rate())
    catalog = EvidenceCatalog(
        overlay_datasets={target.id: (dataset,) for target in aliases.values()}
    )
    with pytest.raises(ValueError, match="different physical targets"):
        evaluate(
            replace(candidates, reactions={target.id: target for target in aliases.values()}),
            catalog,
            Conditions(gas_temperature_K=350),
        )
    # Two references to one physical channel are one quantity subject.
    first = aliases["Ar"]
    second = replace(first, id="second reference to same channel")
    catalog = EvidenceCatalog(
        overlay_datasets={
            first.id: (dataset,),
            second.id: (dataset,),
            "unused reference for another analysis": (normalized_dataset(rate(id="unused")),),
        }
    )
    result = evaluate(
        replace(candidates, reactions={first.id: first, second.id: second}),
        catalog,
        Conditions(gas_temperature_K=350),
    )
    assert {use.value for use in result.data_use.values()} == {1e-15}
    assert all(
        record.reaction_target is None
        for records in catalog.overlay_datasets.values()
        for record in records
    )
