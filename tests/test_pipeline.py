"""Public analysis, canonical persistence, saved views and explicit migration."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from reactgen import export, ingest, needs
from reactgen.case import Case, Conditions, Limits, RequestedReaction
from reactgen.chemistry import parse_state_id
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.pathway import checked_pathway_query
from reactgen.pipeline import analyze
from reactgen.records import Property, ReactionRecord
from tools.migrate_v4 import _reaction_records, migrate

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


def result():
    return analyze(
        Case("analysis", ("Ar",), limits=Limits(max_atoms=1, max_depth=1)),
        EvidenceCatalog.load(None),
    )


def dump(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value), encoding="utf-8")


def test_property_qualification_does_not_change_candidate_scope() -> None:
    case = Case(
        "test",
        ("Ar", "F2"),
        limits=Limits(max_atoms=2, max_depth=3, max_reactions=1500),
    )
    original = EvidenceCatalog.load(FIXTURE)
    changed = replace(
        original,
        state_records=tuple(
            replace(record, status="rejected") for record in original.state_records
        ),
    )
    first = analyze(case, original)
    second = analyze(case, changed)

    def mechanical(analysis):
        return {
            item.key
            for item in analysis.candidates.reactions.values()
            if item.origin == "mechanical"
        }

    assert mechanical(first) == mechanical(second)
    assert first.metadata["supply_state_ids"] == second.metadata["supply_state_ids"]


def test_source_states_reenter_generation_without_becoming_particle_supplies() -> None:
    ground, excited, electron = (parse_state_id(name) for name in ("Ar", "Ar@source_level", "e"))
    assert ground is not None
    assert excited is not None
    assert electron is not None
    declared = replace(excited, classes=frozenset({"feed"}))
    source = ReactionRecord(
        "source-excitation",
        (
            None,
            None,
            ((ground.id, 1.0), (electron.id, 1.0)),
            ((excited.id, 1.0), (electron.id, 1.0)),
        ),
        "electron",
        "excitation",
        (ground, declared, electron),
    )
    contradiction = RequestedReaction("e + Ar -> e + Ne", "excitation")
    refuted = ReactionRecord(
        "refuted inventory",
        contradiction.candidate.equation_key,
        "electron",
        "excitation",
        contradiction.states,
    )
    catalog = EvidenceCatalog(reaction_records=(source, refuted))
    result = analyze(
        Case("source expansion", ("Ar",), limits=Limits(max_atoms=1, max_depth=3)),
        catalog,
    )
    assert excited.id in result.candidates.states
    assert excited.id not in result.metadata["supply_state_ids"]
    assert "feed" not in result.candidates.states[excited.id].classes
    assert "feed" in catalog.reaction_records[0].states[1].classes
    assert any(
        reaction.origin == "mechanical"
        and excited.id in {term.species for term in reaction.reactants}
        for reaction in result.candidates.reactions.values()
    )
    assert "Ne@ground" in result.candidates.states
    assert all(
        term.species != "Ne@ground"
        for reaction in result.candidates.reactions.values()
        for term in reaction.reactants
    )
    assert (
        result.evaluation.reaction_assessments[contradiction.candidate.id]["conservation"].verdict
        == "fail"
    )


def test_rejected_source_is_preserved_only_when_its_channel_is_independently_proposed(
    tmp_path: Path,
) -> None:
    proposed = RequestedReaction("e + Ar+ -> Ar^2+ + 2 e", "ionization")
    source = tmp_path / "source.yaml"
    dump(
        source,
        {
            "snapshot_version": 1,
            "records": [
                {
                    "reaction": proposed.equation,
                    "type": proposed.process,
                    "channel_scope": "product_resolved",
                    "status": "rejected",
                }
            ],
        },
    )
    catalog = EvidenceCatalog.load_paths((source,))
    case = Case(
        "rejected proposal", ("Ar",), supplies=("e", "Ar+"), limits=Limits(max_atoms=1, max_depth=1)
    )
    candidates = analyze(case, catalog).candidates
    assert proposed.candidate.id not in candidates.reactions
    assert "Ar^2+@ground" not in candidates.states

    saved = export.document(analyze(replace(case, reactions=(proposed,)), catalog))
    reaction = next(item for item in saved["reactions"] if item["id"] == proposed.candidate.id)
    assert reaction["origin"] == "requested"
    assert [record["status"] for record in reaction["evidence"]["records"]] == ["rejected"]
    assert reaction["assessments"]["reaction_evidence"]["verdict"] == "unknown"


def test_qualified_source_transform_and_checked_route_do_not_depend_on_snapshot_order(
    tmp_path: Path,
) -> None:
    channel = RequestedReaction("Ar@upper + Ne -> Ar@lower + Ne", "quenching")
    transform = {
        "kind": "level_transition",
        "initial": "Ar@upper",
        "final": "Ar@lower",
        "collider": "Ne@ground",
    }
    good = {
        "id": "good",
        "reaction": channel.equation,
        "type": channel.process,
        "status": "reviewed",
        "review_scope": ["channel_assertion"],
        "transformation": transform,
        "energy_properties": {
            "delta_e_eV": {
                "value": -1,
                "unit": "eV",
                "definition": "products_minus_reactants",
                "status": "reviewed",
                "evidence_tier": "reviewed",
            }
        },
    }
    bad = good | {
        "id": "bad",
        "status": "rejected",
        "transformation": transform | {"initial": "Ar@ground"},
    }
    unrelated = good | {
        "id": "only energy",
        "review_scope": ["delta_e_eV"],
        "transformation": transform | {"initial": "Ar@ground"},
    }
    case = Case(
        "source transformation",
        ("Ne",),
        supplies=("Ar@upper",),
        conditions=Conditions(collision_energy_eV=5, collision_energy_frame="com"),
        limits=Limits(max_atoms=1, max_depth=1),
    )
    source = tmp_path / "source.yaml"
    for records in ([good, bad, unrelated], [unrelated, bad, good]):
        dump(source, {"snapshot_version": 1, "records": records})
        saved = export.document(analyze(case, EvidenceCatalog.load_paths((source,))))
        reaction = next(item for item in saved["reactions"] if item["id"] == channel.candidate.id)
        assert reaction["transformation"] == transform
        assert reaction["assessments"]["consistency"]["verdict"] == "pass"
        assert {record["status"] for record in reaction["evidence"]["records"]} == {
            "reviewed",
            "rejected",
        }
        assert {
            record["transformation"]["initial"] for record in reaction["evidence"]["records"]
        } == {"Ar@upper", "Ar@ground"}
        checked = checked_pathway_query(saved["states"], saved["reactions"], saved["pathways"])
        assert channel.candidate.id in checked["checked"]["reaction_layers"]


def test_deeper_source_chain_cannot_preempt_a_shallower_mechanical_expansion() -> None:
    ground, first, second, electron = (
        parse_state_id(name) for name in ("Ar", "Ar@first", "Ar@second", "e")
    )
    assert all(state is not None for state in (ground, first, second, electron))
    records = tuple(
        ReactionRecord(
            f"source-{parent.id}",
            (
                None,
                None,
                ((parent.id, 1.0), (electron.id, 1.0)),
                ((target.id, 1.0), (electron.id, 1.0)),
            ),
            "electron",
            "excitation",
            (parent, target, electron),
        )
        for parent, target in ((ground, first), (first, second))
    )
    result = analyze(
        Case("depth", ("Ar",), supplies=("e",), limits=Limits(max_atoms=1, max_depth=2)),
        EvidenceCatalog(reaction_records=records),
    ).candidates
    assert result.states[second.id].depth == 1
    assert any(
        row.process == "elastic" and {term.species for term in row.reactants} == {second.id, "e"}
        for row in result.reactions.values()
    )


@pytest.mark.parametrize(
    ("depth", "energy", "verdict"), [(2, 0, "fail"), (2, 20, "pass"), (1, 20, "pass")]
)
def test_requested_intermediate_extends_bounded_discovery_without_becoming_feed(
    depth: int, energy: float, verdict: str
) -> None:
    request = RequestedReaction("e + Ar+ -> Ar^2+ + 2 e", "ionization")
    downstream = RequestedReaction("e + Ar^2+ -> Ar^3+ + 2 e", "ionization")
    disconnected = RequestedReaction("e + Ne^2+ -> Ne^3+ + 2 e", "ionization")
    unbalanced = RequestedReaction("e + Ar+ -> Xe^2+ + 2 e", "ionization")
    catalog = EvidenceCatalog(
        reaction_records=(
            ReactionRecord(
                "synthetic endpoint difference",
                request.candidate.equation_key,
                "electron",
                "ionization",
                request.states,
                channel_scope="energy_relation",
                energy_properties={
                    "delta_e_eV": Property(
                        12.0, "eV", tier="reviewed", definition="products_minus_reactants"
                    )
                },
            ),
            ReactionRecord(
                "downstream channel",
                downstream.candidate.equation_key,
                "electron",
                "ionization",
                downstream.states,
            ),
        )
    )
    analysis = analyze(
        Case(
            "nominated intermediate",
            ("Ar",),
            conditions=Conditions(
                collision_energy_eV=energy,
                collision_energy_frame="com",
                projectile_state="e",
                target_state="Ar+",
            ),
            limits=Limits(max_atoms=1, max_depth=depth),
            supplies=("e", "Ar+"),
            reactions=(request, disconnected, unbalanced),
        ),
        catalog,
    )
    saved = export.document(analysis)
    reactions = analysis.candidates.reactions
    assert saved["pathways"]["seeds"] == ["Ar+@ground", "Ar@ground", "e"]
    assert reactions[request.candidate.id].origin == "requested"
    assert (
        analysis.evaluation.reaction_assessments[request.candidate.id]["energy"].verdict == verdict
    )
    assert reactions[disconnected.candidate.id].depth == 0
    assert reactions[unbalanced.candidate.id].depth == 0
    assert not any(
        {"Ne^3+@ground", "Xe^2+@ground"}.intersection(term.species for term in row.reactants)
        for row in reactions.values()
    )
    assert (downstream.candidate.id in reactions) == (depth == 2)
    if depth == 2:
        assert reactions[downstream.candidate.id].origin == "attested_only"
        assert any(
            row.origin == "mechanical"
            and row.process == "elastic"
            and {term.species for term in row.reactants} == {"e", "Ar^2+@ground"}
            for row in reactions.values()
        )
    assert saved["metadata"]["generation"]["completion"]["attested"] == (depth == 2)
    assert ("Ar^3+@ground" in saved["pathways"]["candidate"]["state_layers"]) == (depth == 2)
    assert ("Ar^3+@ground" in saved["pathways"]["conditioned"]["state_layers"]) == (
        depth == 2 and verdict == "pass"
    )


def test_no_evidence_retains_candidates_and_scopes_conclusions() -> None:
    analysis = result()
    assert analysis.evaluation.state_assessments["Ar@ground"]["state"].verdict == "unknown"
    document = export.document(analysis)
    assert len(document["reactions"]) == len(analysis.candidates.reactions)
    assert set(document["metadata"]["generation"]["completion"]) == {"mechanical", "attested"}
    binding_states = [
        state for state in document["states"] if "electron_binding" in state["assessments"]
    ]
    assert all(
        state["charge"] == -1 and state["state"]["kind"] == "ground" for state in binding_states
    )
    if binding_states:
        assert sum(document["summary"]["judgments"]["states"]["electron_binding"].values()) == len(
            binding_states
        )
        binding_coverage = document["summary"]["coverage"]["judgments"]["states"][
            "electron_binding"
        ]
        assert binding_coverage["total"] == len(binding_states)


def test_published_tables_are_deterministic_and_share_the_same_conclusions(tmp_path: Path) -> None:
    analysis = result()
    first, second = tmp_path / "first", tmp_path / "second"
    committed = export.write(first, analysis)
    export.write(second, analysis)
    files = {"result.yaml", *committed["helper_views"]}
    assert {
        path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file()
    } == files
    for name in files:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    document = export.read(first, verify_views=True)
    assert committed == document
    assert document["input"]["gases"] == ["Ar"]
    assert document["metadata"]["schema_version"] == 5
    assert document["summary"]["reaction_count"] == len(document["reactions"])
    assert all("kinetic_effects" not in reaction for reaction in document["reactions"])


@pytest.mark.parametrize("change", ["hash", "content", "missing", "extra"])
def test_saved_result_rejects_view_hashes_detached_from_canonical_content(
    tmp_path: Path, change: str
) -> None:
    export.write(tmp_path, result())
    document = export.read(tmp_path, verify_views=True)
    if change == "hash":
        expected = document["helper_views"]["states.csv"]
        document["helper_views"]["states.csv"] = ("0" if expected[0] != "0" else "1") + expected[1:]
    elif change == "content":
        document["states"][0]["assessments"]["state"]["message"] = "Changed canonical reason"
    elif change == "missing":
        del document["helper_views"]["states.csv"]
    else:
        document["helper_views"]["extra.csv"] = "0" * 64
    dump(tmp_path / "result.yaml", document)

    for verify_views in (False, True):
        with pytest.raises(ValueError, match="helper_views|helper view hashes"):
            export.read(tmp_path, verify_views=verify_views)


@pytest.mark.parametrize("location", ["selected", "alternative"])
def test_saved_result_rejects_cyclic_calculation_inputs(location: str) -> None:
    document = export.document(result())
    calculations = next(
        row["thermochemical_calculations"]
        for row in document["reactions"]
        if row["process"] == "elastic"
    )
    name = "state_energy_difference_eV"
    calculation = calculations[name]
    inputs = [{"calculation": name, "coefficient": 1.0}]
    if location == "selected":
        calculation["inputs"] = inputs
    else:
        calculation["alternatives"] = [
            {"value": 0.0, "unit": "eV", "operation": "test", "inputs": inputs, "conditions": {}}
        ]
    document["helper_views"] = {
        name: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for name, content in export.csv_views(document).items()
    }
    with pytest.raises(ValueError, match="cyclic calculation references"):
        export.validate(document)


def selected_data_use(status: str = "coefficient") -> dict:
    transforms = ["surface_flux_conversion"] if status == "needs_transform" else []
    unit = "1" if transforms else "m3/s"
    return {
        "status": status,
        "reason": "test numerical result",
        "dataset_id": "selected",
        "kind": "sticking_coefficient" if transforms else "rate_coefficient",
        "value": 0,
        "unit": unit,
        "required_inputs": [],
        "required_transforms": transforms,
        "estimated": False,
        "datasets": [
            {
                "dataset_id": "selected",
                "status": "valid",
                "reason": "test applicable dataset",
                "value": 0,
                "unit": unit,
                "required_inputs": [],
                "required_transforms": list(transforms),
            }
        ],
    }


def document_with_use(use: dict) -> dict:
    document = export.document(result())
    # These fixtures exercise historical schema-5 fields. Current typed work
    # and dependent-claim invariants are covered by responsibility_contracts.
    document["metadata"]["helper_view_format"] = 3
    reaction = document["reactions"][0]
    reaction["data_use"] = use
    # Saved numerical selections must refer to the scientific evidence they
    # select. This fixture preserves that link without rerunning any model.
    reaction["evidence"]["overlay_datasets"] = [{"id": "selected", "kind": use["kind"]}]
    document["summary"] = export.summary(document["states"], document["reactions"])
    document["helper_views"] = {
        name: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for name, content in export.csv_views(document).items()
    }
    return document


def test_legacy_saved_coefficient_can_be_zero(tmp_path: Path) -> None:
    document = document_with_use(selected_data_use())
    dump(tmp_path / "result.yaml", document)
    assert export.read(tmp_path)["reactions"][0]["data_use"]["value"] == 0


def test_legacy_saved_use_can_require_selection_without_claiming_a_value() -> None:
    use = selected_data_use()
    use.update(
        status="needs_input",
        dataset_id=None,
        kind=None,
        value=None,
        unit=None,
        required_inputs=["rate_law_selection"],
    )
    export.validate(document_with_use(use))


@pytest.mark.parametrize(
    ("kind", "value", "unit"),
    [
        ("sticking_coefficient", 0.4, "1"),
        ("cross_section", None, "m2"),
    ],
)
def test_saved_use_retains_probabilities_or_curves_pending_conversion(
    kind: str, value: float | None, unit: str
) -> None:
    use = selected_data_use("needs_transform")
    use.update(kind=kind, value=value, unit=unit)
    use["datasets"][0].update(value=value, unit=unit)
    export.validate(document_with_use(use))


@pytest.mark.parametrize(
    ("status", "use_changes", "dataset_changes"),
    [
        ("coefficient", {"value": None}, {"value": None}),
        ("coefficient", {"dataset_id": None}, {}),
        ("coefficient", {"dataset_id": "absent"}, {}),
        ("coefficient", {}, {"status": "invalid"}),
        ("coefficient", {}, {"value": 1}),
        ("coefficient", {"required_inputs": ["unknown"]}, {"required_inputs": ["unknown"]}),
        ("coefficient", {"kind": "sticking_coefficient", "unit": "1"}, {"unit": "1"}),
        ("needs_transform", {"value": 1.1}, {"value": 1.1}),
    ],
)
def test_saved_use_rejects_status_value_and_selection_contradictions(
    status: str, use_changes: dict, dataset_changes: dict
) -> None:
    use = selected_data_use(status)
    use.update(use_changes)
    use["datasets"][0].update(dataset_changes)
    with pytest.raises(ValueError, match="data_use|data_use selection"):
        export.validate(document_with_use(use))


def test_saved_use_rejects_duplicate_dataset_assessments() -> None:
    use = selected_data_use()
    use["datasets"].append(deepcopy(use["datasets"][0]))
    with pytest.raises(ValueError, match="duplicate data_use dataset IDs"):
        export.validate(document_with_use(use))


@pytest.mark.parametrize(
    "change", ["id", "charge", "phase", "reference", "verdict", "extra", "summary", "input"]
)
def test_saved_result_rejects_identity_and_schema_contradictions(change: str) -> None:
    document = export.document(result())
    if change == "id":
        document["states"][0]["id"] = "bad"
    elif change == "charge":
        document["states"][0]["charge"] += 1
    elif change == "phase":
        document["states"][0]["phase"] = "solid"
    elif change == "reference":
        document["reactions"][0]["reactants"][0]["species"] = "missing"
    elif change == "verdict":
        document["reactions"][0]["assessments"]["kinetics"]["verdict"] = "ready"
    elif change == "extra":
        document["unexpected"] = True
    elif change == "input":
        document["input"]["gases"] = ["CF4"]
    else:
        document["summary"]["reaction_count"] += 1
    with pytest.raises(ValueError, match=".+"):
        export.validate(document)


def test_failed_canonical_replace_preserves_previous_result(tmp_path: Path, monkeypatch) -> None:
    export.write(tmp_path, result())
    previous = (tmp_path / "result.yaml").read_bytes()
    original = Path.replace

    def replace(path, target):
        if Path(target).name == "result.yaml":
            raise OSError("injected commit failure")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError, match="commit failure"):
        export.write(
            tmp_path,
            analyze(
                Case("changed", ("Ar",), limits=Limits(max_atoms=1, max_depth=1)),
                EvidenceCatalog.load(None),
            ),
        )
    assert (tmp_path / "result.yaml").read_bytes() == previous
    export.read(tmp_path, verify_views=True)
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_csv_replace_leaves_canonical_readable_and_repairable(
    tmp_path: Path, monkeypatch
) -> None:
    export.write(tmp_path, result())
    original = Path.replace

    def replace(path, target):
        if Path(target).name == "states.csv":
            raise OSError("injected view failure")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    # Different gases change both views and establish an actual mixed-view case.
    updated = analyze(
        Case(
            "changed",
            ("Ar", "F2"),
            limits=Limits(max_atoms=2, max_depth=1, max_reactions=200),
        ),
        EvidenceCatalog.load(None),
    )
    with pytest.raises(export.PartialOutputError, match="result.yaml saved"):
        export.write(tmp_path, updated)
    document = export.read(tmp_path)
    assert document["input"]["gases"] == ["Ar", "F2"]
    with pytest.raises(ValueError, match="stale"):
        export.read(tmp_path, verify_views=True)
    monkeypatch.setattr(Path, "replace", original)
    export.rebuild_views(tmp_path, tmp_path)
    export.read(tmp_path, verify_views=True)


@pytest.mark.parametrize(
    "document",
    [
        {"gases": "Ar"},
        {"gases": []},
        {"gases": ["Ar"], "surfaces": "SiO2"},
        {"gases": ["Ar"], "conditions": {"pressure_Pa": 1}},
        {"gases": ["Ar"], "conditions": {"gas_temperature_K": True}},
        {"gases": ["Ar"], "conditions": {"gas_temperature_K": float("nan")}},
        {"gases": ["Ar"], "conditions": {"electron_temperature_eV": 0}},
        {"gases": ["Ar"], "limits": {"max_depth": 1.5}},
        {"gases": ["Ar"], "limits": {"max_species": True}},
        {"gases": ["Ar"], "limits": {"max_charge_abs": 2}},
        {"gases": ["Ar"], "scenario": "etch"},
    ],
)
def test_input_boundary_rejects_unusable_or_ambiguous_fields(document: dict) -> None:
    with pytest.raises(ValueError, match=".+"):
        Case.from_document(document)


def test_input_normalization_and_supported_quantity_values() -> None:
    case = Case.from_document(
        {"gases": ["AR", "Ar", "F2"], "conditions": {"gas_temperature_K": "3.0e2"}}
    )
    assert case.gases == ("Ar", "F2")
    assert case.conditions.value_of("gas_temperature") == 300
    assert Conditions(ion_energy_eV=2).value_of("ion_energy") == 2


def test_formula_and_file_cli_share_one_result(tmp_path: Path) -> None:
    input_path = tmp_path / "input.yaml"
    dump(input_path, {"gases": ["Ar"]})
    first, second = tmp_path / "first", tmp_path / "second"
    assert main(["analyze", "Ar", "--out", str(first)]) == 0
    assert main(["analyze", "--input", str(input_path), "--out", str(second)]) == 0
    assert (first / "result.yaml").read_bytes() == (second / "result.yaml").read_bytes()
    assert main(["analyze", "Ar", "--input", str(input_path), "--out", str(second)]) == 2
    assert main(["analyze", "--out", str(second)]) == 2


def test_explicit_missing_evidence_is_an_error(tmp_path: Path) -> None:
    out = tmp_path / "result"
    assert main(["analyze", "Ar", "--evidence", str(tmp_path / "missing"), "--out", str(out)]) == 2
    assert not out.exists()


def test_partial_generation_is_saved_with_explicit_scopes(tmp_path: Path) -> None:
    input_path = tmp_path / "input.yaml"
    dump(input_path, {"gases": ["SF6"], "limits": {"max_depth": 1}})
    assert main(["analyze", "--input", str(input_path), "--out", str(tmp_path / "out")]) == 1
    generation = export.read(tmp_path / "out")["metadata"]["generation"]
    assert generation["complete"] is False
    assert generation["completion"]["mechanical"] is False
    assert generation["stop_reason"] == "max_depth=1"


def test_needs_keeps_repair_work_even_if_another_judgment_failed() -> None:
    document = export.document(result())
    item = document["reactions"][0]
    item["assessments"]["kinetics"] = {"verdict": "fail", "message": "invalid dataset", "basis": []}
    item["assessments"]["reaction_evidence"] = {
        "verdict": "unknown",
        "message": "missing channel proof",
        "basis": [],
    }
    backlog = needs.build(document, detail=True)["details"]
    assert any(
        row["id"] == item["id"] and row["responsibility"] == "failed_proposition" for row in backlog
    )
    assert any(
        row["id"] == item["id"] and row["judgment"] == "reaction_evidence" for row in backlog
    )


def test_saved_views_and_needs_never_reanalyze(tmp_path: Path, monkeypatch) -> None:
    export.write(tmp_path / "out", result())

    def forbidden(*args):
        raise AssertionError("saved views must not analyze")

    monkeypatch.setattr("reactgen.cli.analyze", forbidden)
    assert main(["needs", str(tmp_path / "out")]) == 0
    assert (
        main(["view", str(tmp_path / "out"), "--kind", "csv", "--out", str(tmp_path / "tables")])
        == 0
    )
    assert main(["view", str(tmp_path / "out"), "--kind", "dnt"]) == 0
    assert yaml.safe_load((tmp_path / "out/dnt/dnt_inputs.yaml").read_text())["pairs"] == []


def test_dnt_handoff_retains_missing_dipole_and_independent_energy_values(tmp_path: Path) -> None:
    result_path = tmp_path / "result"
    catalog = EvidenceCatalog.load(FIXTURE)
    case = Case(
        "ion collision",
        ("Ar", "F2"),
        limits=Limits(max_atoms=2, max_depth=1),
        supplies=("e", "Ar+"),
    )
    saved = export.write(result_path, analyze(case, catalog))
    assert main(["view", str(result_path), "--kind", "dnt"]) == 0
    payload = yaml.safe_load((result_path / "dnt/dnt_inputs.yaml").read_text(encoding="utf-8"))
    pairs = {pair["target"]["state"]: pair for pair in payload["pairs"]}
    assert set(pairs) == {"Ar@ground", "F2@ground"}
    assert all(pair["projectile"]["state"] == "Ar+@ground" for pair in pairs.values())
    assert pairs["Ar@ground"]["neutral_dipole_model_hint"] == "dnt_plus"
    assert pairs["F2@ground"]["neutral_dipole_model_hint"] is None
    assert pairs["F2@ground"]["target"]["dipole_moment_D"]["status"] == "unavailable"

    elastic = next(row for row in pairs["Ar@ground"]["channels"] if row["process"] == "elastic")
    assert elastic["endpoint_difference"]["value"] == 0.0
    assert elastic["declared_threshold_eV"] is None
    assert export.read(result_path, verify_views=True) == saved


def test_ingest_checks_declared_equation_even_with_explicit_id(tmp_path: Path) -> None:
    analysis = result()
    export.write(tmp_path / "out", analysis)
    elastic = next(
        item for item in analysis.candidates.reactions.values() if item.process == "elastic"
    )
    snapshot = tmp_path / "snapshot.yaml"
    dump(
        snapshot,
        {
            "records": [
                {
                    "reaction_id": elastic.id,
                    "reaction": "e + Ar -> 2 e + Ar+",
                    "type": "ionization",
                    "value": 1,
                    "form": "constant",
                    "unit": "m3/s",
                },
                {
                    "species": "Ar@ground",
                    "phase": "solid",
                    "property": "mass_amu",
                    "value": 40,
                    "unit": "u",
                },
            ]
        },
    )
    report = ingest.ingest(snapshot, tmp_path / "out", tmp_path / "overlay.yaml")
    assert report.accepted == 0
    assert [item["reason"] for item in report.review] == [
        "reaction ID contradicts declared channel",
        "physical identity mismatch",
    ]


def test_legacy_files_are_not_silently_overwritten(tmp_path: Path) -> None:
    dump(tmp_path / "states.yaml", {"metadata": {"schema_version": 4}, "states": []})
    with pytest.raises(ValueError, match="migration"):
        export.write(tmp_path, result())


def legacy(tmp_path: Path) -> tuple[Path, Path]:
    input_path = tmp_path / "old_input.yaml"
    dump(input_path, {"gases": ["Ar"], "conditions": {"pressure_Pa": 1, "gas_temperature_K": 300}})
    bundle = tmp_path / "old_bundle"
    bundle.mkdir()
    state = {
        "id": "Ar@ground",
        "composition": {"Ar": 1},
        "charge": 0,
        "assessments": {"state": {"verdict": "pass"}},
        "evidence": {"records": []},
    }
    dump(bundle / "states.yaml", {"metadata": {"schema_version": 4}, "states": [state]})
    dump(bundle / "reactions.yaml", {"metadata": {"schema_version": 4}, "reactions": []})
    dump(bundle / "selected.yaml", {"readiness": {"direct_rate_ready": True}})
    return input_path, bundle


def test_migration_preserves_originals_and_recomputes_judgments(tmp_path: Path) -> None:
    input_path, bundle = legacy(tmp_path)
    migrate(input_path, bundle, tmp_path / "new")
    document = export.read(tmp_path / "new")
    assert document["states"][0]["assessments"]["state"]["verdict"] == "unknown"
    archived = yaml.safe_load(
        (tmp_path / "new/migration/input_v4.yaml").read_text(encoding="utf-8")
    )
    assert archived["conditions"]["pressure_Pa"] == 1
    assert "pressure_Pa" not in document["input"]["conditions"]
    assert (tmp_path / "new/migration/selected.yaml").read_bytes() == (
        bundle / "selected.yaml"
    ).read_bytes()


def test_migration_keeps_unidentified_related_records_only_in_archive(tmp_path: Path) -> None:
    input_path, bundle = legacy(tmp_path)
    related = {
        "id": "unidentified-total",
        "channel_scope": "total",
        "source": {"source_id": "total-source"},
    }
    reaction = {
        "reactants": [{"species": "Ar@ground"}],
        "products": [{"species": "Ar@ground"}],
        "family": "neutral",
        "process": "elastic",
        "evidence": {"related_total_process_records": [related]},
    }
    original = {"metadata": {"schema_version": 4}, "reactions": [reaction]}
    dump(bundle / "reactions.yaml", original)
    migrate(input_path, bundle, tmp_path / "new")
    restored = yaml.safe_load(
        (tmp_path / "new/migration/evidence.yaml").read_text(encoding="utf-8")
    )
    assert restored["records"] == []
    assert (
        yaml.safe_load((tmp_path / "new/migration/reactions.yaml").read_text(encoding="utf-8"))
        == original
    )


@pytest.mark.parametrize(
    "group", ["related_total_process_records", "related_physical_process_records"]
)
def test_migration_preserves_related_records_own_target_and_scope(
    tmp_path: Path, group: str
) -> None:
    related = {
        "reaction": "He@ground -> He@ground",
        "family": "neutral",
        "process": "elastic",
        "channel_scope": "total",
        "source": {"source_id": "helium-source"},
    }
    reaction = {
        "reactants": [{"species": "Ar@ground"}],
        "products": [{"species": "Ar@ground"}],
        "family": "neutral",
        "process": "elastic",
        "evidence": {"exact_channel_records": [], group: [related]},
    }
    original = deepcopy(reaction)
    records = _reaction_records(
        [reaction],
        tmp_path,
        {"Ar@ground": "Ar@ground;phase=unknown", "He@ground": "He@ground;phase=unknown"},
    )
    assert records[0]["reaction"] == "He@ground;phase=unknown -> He@ground;phase=unknown"
    assert records[0]["channel_scope"] == "total"
    assert records[0]["source"] == {"source_id": "helium-source"}
    assert reaction == original


@pytest.mark.parametrize("written", ["invalid equation", "Ne@ground -> Ne@ground"])
def test_migration_rejects_invalid_or_unidentified_explicit_related_target(
    tmp_path: Path, written: str
) -> None:
    reaction = {
        "reactants": [{"species": "Ar@ground"}],
        "products": [{"species": "Ar@ground"}],
        "family": "neutral",
        "process": "elastic",
        "evidence": {"related_total_process_records": [{"reaction": written}]},
    }
    with pytest.raises(ValueError, match="legacy"):
        _reaction_records([reaction], tmp_path, {"Ar@ground": "Ar@ground;phase=unknown"})


def test_migration_rejects_raw_terms_before_consolidation(tmp_path: Path) -> None:
    reaction = {
        "reactants": [{"species": "Ar@ground", "n": -1}, {"species": "Ar@ground", "n": 2}],
        "products": [{"species": "Ar@ground"}],
        "family": "neutral",
        "process": "elastic",
    }
    with pytest.raises(ValueError, match="positive"):
        _reaction_records([reaction], tmp_path, {"Ar@ground": "Ar@ground;phase=unknown"})


def test_migration_rejects_ambiguous_multivalent_identity(tmp_path: Path) -> None:
    input_path, bundle = legacy(tmp_path)
    document = yaml.safe_load((bundle / "states.yaml").read_text(encoding="utf-8"))
    document["states"][0].update(id="Ar2+@ground", composition={"Ar": 1}, charge=2)
    dump(bundle / "states.yaml", document)
    with pytest.raises(ValueError, match="ambiguous legacy"):
        migrate(input_path, bundle, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_invalid_source_number_remains_repairable_without_blocking_other_results(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "source.yaml"
    dump(
        snapshot,
        {
            "records": [
                {
                    "reaction": "e + Ar -> e + Ar",
                    "family": "electron",
                    "type": "elastic",
                    "form": "constant",
                    "params": {"value": float("nan")},
                    "unit": "m3/s",
                    "status": "reviewed",
                    "source": {"citation": "test declaration"},
                    "validity": {
                        "quantity": "gas_temperature",
                        "minimum": 100,
                        "maximum": 1000,
                        "unit": "K",
                    },
                }
            ]
        },
    )
    analysis = analyze(
        Case("test", ("Ar",), Conditions(gas_temperature_K=300)),
        EvidenceCatalog.load_paths((snapshot,)),
    )
    export.write(tmp_path / "out", analysis)
    document = export.read(tmp_path / "out")
    elastic = next(item for item in document["reactions"] if item["process"] == "elastic")
    assert elastic["data_use"]["status"] == "unavailable"
    assert elastic["data_use"]["datasets"][0]["status"] == "invalid"
    assert elastic["evidence"]["records"][0]["datasets"][0]["params"]["value"] == "nan"
    assert document["summary"]["reaction_count"] > 0


def test_needs_retains_invalid_dataset_when_an_alternative_is_selected() -> None:
    document = export.document(result())
    candidate = document["reactions"][0]
    candidate["data_use"].update(
        status="coefficient",
        datasets=[
            {
                "dataset_id": "broken",
                "status": "invalid",
                "reason": "wrong units",
                "scope": "native representation",
                "requirements": [
                    {
                        "responsibility": "source_review",
                        "target": "broken",
                        "quantity": "numerical_representation",
                        "reason": "wrong units",
                    }
                ],
            }
        ],
    )
    assert any(
        item["subject"] == "dataset" and item["id"] == "broken"
        for item in needs.build(document, detail=True)["details"]
    )


def test_ingest_does_not_promote_unspecified_phase_to_gas(tmp_path: Path) -> None:
    export.write(tmp_path / "out", result())
    snapshot = tmp_path / "source.yaml"
    dump(
        snapshot,
        {
            "records": [
                {"species": "Ar", "property": "enthalpy_formation_eV", "value": 1, "unit": "eV"}
            ]
        },
    )
    report = ingest.ingest(snapshot, tmp_path / "out", tmp_path / "overlay.yaml")
    assert report.accepted == 0
    assert report.review[0]["reason"] == "physical phase unspecified"


def state_snapshot_record() -> dict:
    return {
        "species": "Ar@ground",
        "phase": "gas",
        "status": "reviewed",
        "existence": "confirmed",
        "existence_source": "explicit state identification",
        "property": "mass_amu",
        "value": 40,
        "unit": "u",
        "evidence_tier": "imported",
        "thermo": {
            "low": [2.5, 0, 0, 0, 0, 0, 0],
            "high": [2.5, 0, 0, 0, 0, 0, 0],
            "t_min": 300,
            "t_mid": 1000,
            "t_max": 5000,
            "phase": "gas",
            "standard_pressure_Pa": 101325,
            "source": "independent fit declaration",
            "evidence_tier": "reviewed",
        },
        "configuration": "declared configuration",
        "term": "declared term",
        "J": "0",
        "parity": "even",
        "degeneracy": 1,
        "lifetime_s": 2,
        "members": [],
        "excitation_energy_eV": 0,
    }


def test_ingest_retains_all_state_payloads_and_their_independent_qualifications(
    tmp_path: Path,
) -> None:
    export.write(tmp_path / "out", result())
    record = state_snapshot_record()
    source = {"citation": "snapshot source", "license": "declared license"}
    dump(tmp_path / "snapshot.yaml", {"source": source, "records": [record]})
    overlay = tmp_path / "overlay.yaml"
    report = ingest.ingest(tmp_path / "snapshot.yaml", tmp_path / "out", overlay)
    assert report.accepted == 1
    assert not report.review
    held = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    identity = held["state_records"]["Ar@ground"][0]
    for name in (
        "existence",
        "existence_source",
        "configuration",
        "term",
        "J",
        "parity",
        "degeneracy",
        "lifetime_s",
        "members",
        "excitation_energy_eV",
    ):
        assert identity[name] == record[name]
    assert identity["source"] == source
    assert identity["status"] == "reviewed"
    assert identity["properties"]["mass_amu"]["tier"] == "imported"
    assert identity["properties"]["excitation_energy_eV"]["tier"] == "imported"
    assert held["state_records"]["Ar@ground"][0]["thermo"]["tier"] == "reviewed"
    candidate = parse_state_id("Ar@ground")
    assert candidate is not None
    direct = EvidenceCatalog.load_paths((tmp_path / "snapshot.yaml",)).state(candidate).preferred
    placed = EvidenceCatalog.load_paths((overlay,)).state(candidate).preferred
    assert direct is not None
    assert placed is not None
    for name in (
        "existence",
        "existence_source",
        "configuration",
        "term",
        "j",
        "parity",
        "degeneracy",
        "lifetime_s",
        "members",
        "energy_eV",
        "properties",
        "thermo",
    ):
        assert getattr(placed, name) == getattr(direct, name)
    assert all(placed.source[key] == value for key, value in direct.source.items())


def test_ingest_preserves_the_supported_thermo_property_snapshot_form(tmp_path: Path) -> None:
    export.write(tmp_path / "out", result())
    fit = state_snapshot_record()["thermo"]
    dump(
        tmp_path / "snapshot.yaml",
        {"records": [{"species": "Ar", "phase": "gas", "property": "thermo", "value": fit}]},
    )
    report = ingest.ingest(tmp_path / "snapshot.yaml", tmp_path / "out", tmp_path / "overlay.yaml")
    assert report.accepted == 1
    held = yaml.safe_load((tmp_path / "overlay.yaml").read_text(encoding="utf-8"))
    assert set(held) == {"state_records"}
    assert held["state_records"]["Ar@ground"][0]["thermo"]["source"] == fit["source"]
    assert held["state_records"]["Ar@ground"][0]["thermo"]["tier"] == "reviewed"


@pytest.mark.parametrize("section", ["states", "properties", "thermo"])
def test_ingest_keeps_independent_state_declarations_without_partial_merging(
    tmp_path: Path, section: str
) -> None:
    export.write(tmp_path / "out", result())
    record = state_snapshot_record()
    if section == "states":
        previous = {"states": {"Ar@ground": {"term": "different declared term"}}}
    elif section == "properties":
        previous = {"properties": {"Ar@ground": {"mass_amu": {"value": 99, "unit": "u"}}}}
    else:
        previous = {"thermo": {"Ar@ground": {**record["thermo"], "source": "different source"}}}
    source = {"citation": "snapshot source"}
    dump(tmp_path / "snapshot.yaml", {"source": source, "records": [record]})
    dump(tmp_path / "overlay.yaml", previous)
    report = ingest.ingest(tmp_path / "snapshot.yaml", tmp_path / "out", tmp_path / "overlay.yaml")
    assert report.accepted == 1
    assert report.review == []
    placed = yaml.safe_load((tmp_path / "overlay.yaml").read_text(encoding="utf-8"))
    assert placed[section] == previous[section]
    independent = placed["state_records"]["Ar@ground"][0]
    assert independent["term"] == record["term"]
    assert independent["properties"]["mass_amu"]["value"] == record["value"]
    assert independent["thermo"]["source"] == record["thermo"]["source"]
    assert independent["source_declaration"]["snapshot_source"] == source
    assert independent["source_declaration"]["existence"] == record["existence"]


def test_ingest_rejects_state_declarations_that_contradict_the_matched_identity(
    tmp_path: Path,
) -> None:
    export.write(tmp_path / "out", result())
    record = {**state_snapshot_record(), "state": {"kind": "electronic"}}
    dump(tmp_path / "snapshot.yaml", {"records": [record]})
    report = ingest.ingest(tmp_path / "snapshot.yaml", tmp_path / "out", tmp_path / "overlay.yaml")
    assert report.accepted == 0
    assert report.review[0]["reason"] == "physical state declaration mismatch"
    assert report.review[0]["original_record"] == record
    assert yaml.safe_load((tmp_path / "overlay.yaml").read_text(encoding="utf-8")) == {}


def test_migration_preserves_declared_state_representation(tmp_path: Path) -> None:
    from reactgen.chemistry import parse_state_id

    input_path, bundle = legacy(tmp_path)
    declaration = {"kind": "electronic", "resolution": "lumped", "label": "4s"}
    state = {
        "id": "Ar@4s",
        "composition": {"Ar": 1},
        "charge": 0,
        "state": declaration,
        "evidence": {
            "match": "exact",
            "records": [
                {
                    "state": declaration,
                    "properties": {
                        "mass_amu": {"value": 40, "unit": "u", "tier": "curated"},
                    },
                }
            ],
        },
    }
    dump(bundle / "states.yaml", {"metadata": {"schema_version": 4}, "states": [state]})
    migrate(input_path, bundle, tmp_path / "new")
    snapshot = yaml.safe_load(
        (tmp_path / "new/migration/evidence.yaml").read_text(encoding="utf-8")
    )
    parsed = parse_state_id(snapshot["records"][0]["species"])
    assert parsed is not None
    assert parsed.state.kind == "electronic"
    assert parsed.state.resolution == "lumped"
    assert parsed.phase == "unknown"
    assert snapshot["records"][0]["evidence_tier"] == "imported"
