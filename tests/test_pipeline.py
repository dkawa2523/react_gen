"""Public analysis, canonical persistence, saved views and explicit migration."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from reactgen import export, ingest, needs
from reactgen.case import Case, Conditions
from reactgen.chemistry import parse_state_id
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from tools.migrate_v4 import migrate

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


def result():
    return analyze(Case("analysis", ("Ar",)), EvidenceCatalog.load(None))


def dump(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value), encoding="utf-8")


def test_evidence_does_not_change_mechanical_candidates() -> None:
    case = Case("test", ("Ar", "F2"))
    empty = analyze(case, EvidenceCatalog.load(None))
    filled = analyze(case, EvidenceCatalog.load(FIXTURE))

    def mechanical(analysis):
        return {
            item.key
            for item in analysis.candidates.reactions.values()
            if item.origin == "mechanical"
        }

    assert mechanical(empty) == mechanical(filled)


def test_no_evidence_retains_candidates_and_scopes_conclusions() -> None:
    analysis = result()
    assert analysis.evaluation.state_assessments["Ar@ground"]["state"].verdict == "unknown"
    document = export.document(analysis)
    assert len(document["reactions"]) == len(analysis.candidates.reactions)
    assert set(document["metadata"]["generation"]["completion"]) == {"mechanical", "attested"}
    assert "selection" not in document
    assert "readiness" not in document
    assert "predictive" in document["summary"]["interpretation"]


def test_three_files_are_deterministic_and_share_the_same_conclusions(tmp_path: Path) -> None:
    analysis = result()
    first, second = tmp_path / "first", tmp_path / "second"
    export.write(first, analysis)
    export.write(second, analysis)
    assert {path.name for path in first.iterdir()} == set(export.PUBLIC_FILES)
    for name in export.PUBLIC_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    document = export.read(first, verify_views=True)
    assert document["input"]["gases"] == ["Ar"]
    assert document["metadata"]["schema_version"] == 5
    assert document["summary"]["reaction_count"] == len(document["reactions"])


@pytest.mark.parametrize("change", ["hash", "content", "missing", "extra"])
def test_saved_result_rejects_view_hashes_detached_from_canonical_content(
    tmp_path: Path, change: str, monkeypatch
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

    def forbidden(*args):
        raise AssertionError("integrity validation must not reanalyze")

    monkeypatch.setattr("reactgen.pipeline.analyze", forbidden)
    for verify_views in (False, True):
        with pytest.raises(ValueError, match="helper_views|helper view hashes"):
            export.read(tmp_path, verify_views=verify_views)


def selected_data_use(status: str = "coefficient") -> dict:
    inputs = ["gas_temperature"] if status == "needs_input" else []
    transforms = ["surface_flux_conversion"] if status == "needs_transform" else []
    unit = "1" if transforms else "m3/s"
    return {
        "status": status,
        "reason": "test numerical result",
        "dataset_id": "selected",
        "kind": "sticking_coefficient" if transforms else "rate_coefficient",
        "value": 0,
        "unit": unit,
        "required_inputs": inputs,
        "required_transforms": transforms,
        "estimated": False,
        "datasets": [
            {
                "dataset_id": "selected",
                "status": "needs_input" if inputs else "valid",
                "reason": "test applicable dataset",
                "value": 0,
                "unit": unit,
                "required_inputs": list(inputs),
                "required_transforms": list(transforms),
            }
        ],
    }


def document_with_use(use: dict) -> dict:
    document = export.document(result())
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


@pytest.mark.parametrize("status", ["coefficient", "needs_input", "needs_transform"])
def test_saved_use_accepts_zero_and_selected_values_without_rerunning_calculations(
    tmp_path: Path, status: str, monkeypatch
) -> None:
    document = document_with_use(selected_data_use(status))
    dump(tmp_path / "result.yaml", document)

    def forbidden(*args):
        raise AssertionError("saved values must not be recalculated")

    monkeypatch.setattr("reactgen.numeric.data_use", forbidden)
    assert export.read(tmp_path)["reactions"][0]["data_use"]["value"] == 0


@pytest.mark.parametrize("status", ["unavailable", "conflict", "needs_input"])
def test_saved_use_allows_unselected_results_and_missing_selection(status: str) -> None:
    use = selected_data_use()
    use.update(status=status, dataset_id=None, kind=None, value=None, unit=None)
    if status in {"needs_input", "conflict"}:
        use["required_inputs"] = ["rate_law_selection"]
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
        ("coefficient", {"value": -1}, {"value": -1}),
        ("coefficient", {"unit": None}, {"unit": None}),
        ("coefficient", {"kind": None}, {}),
        ("coefficient", {"dataset_id": None}, {}),
        ("coefficient", {"dataset_id": "absent"}, {}),
        ("coefficient", {}, {"status": "invalid"}),
        ("coefficient", {}, {"value": 1}),
        ("coefficient", {}, {"unit": "s-1"}),
        ("coefficient", {"required_inputs": ["unknown"]}, {"required_inputs": ["unknown"]}),
        ("coefficient", {"required_transforms": ["unknown"]}, {}),
        ("coefficient", {"status": "needs_input"}, {}),
        ("coefficient", {"status": "needs_transform"}, {}),
        ("needs_transform", {"required_inputs": ["incident_flux"]}, {}),
        ("coefficient", {"status": "unavailable"}, {}),
        ("coefficient", {"status": "conflict"}, {}),
        ("coefficient", {"status": "conflict", "dataset_id": None, "kind": None, "unit": None}, {}),
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
        document["policy"] = "review"
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
        export.write(tmp_path, analyze(Case("changed", ("Ar",)), EvidenceCatalog.load(None)))
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
    updated = analyze(Case("changed", ("Ar", "F2")), EvidenceCatalog.load(None))
    with pytest.raises(export.PartialOutputError, match="result.yaml saved"):
        export.write(tmp_path, updated)
    document = export.read(tmp_path)
    assert document["input"]["gases"] == ["Ar", "F2"]
    with pytest.raises(ValueError, match="stale"):
        export.read(tmp_path, verify_views=True)
    monkeypatch.setattr(Path, "replace", original)
    export.rebuild_views(document, tmp_path)
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
