"""Scientific evidence assertions, identity and preservation boundaries."""

from __future__ import annotations

import shutil
from dataclasses import asdict, replace
from pathlib import Path

import pytest
import yaml

from acquire import additivity, asd, snapshot
from reactgen import adopt, derive, export, ingest
from reactgen.assessment import assess_state
from reactgen.case import Case, Conditions
from reactgen.chemistry import candidate_state, parse_state_id
from reactgen.evidence import EvidenceCatalog, registry_reaction_candidate
from reactgen.generate import candidates
from reactgen.model import CandidateSet
from reactgen.pipeline import analyze
from reactgen.records import (
    FormationReference,
    NumericDataset,
    Property,
    RegistryState,
    StateRecord,
    Validity,
    dataset_payload,
    normalized_dataset,
    normalized_property,
    normalized_thermo,
)
from reactgen.registry import Registry

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


def write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_reviewed_property_does_not_attest_state_existence(tmp_path):
    overlay = write_yaml(
        tmp_path / "overlay.yaml",
        {
            "properties": {
                "CF4-@ground": {
                    "mass_amu": {"value": 88.0, "unit": "amu", "evidence_tier": "reviewed"}
                }
            }
        },
    )
    state = parse_state_id("CF4-@ground")
    assert state is not None
    evidence = EvidenceCatalog.load_paths((overlay,)).state(state)
    assert evidence.match == "exact"
    assert evidence.preferred is not None
    assert evidence.preferred.existence == "unknown"


def test_only_explicit_existence_assertion_has_its_own_source(tmp_path):
    overlay = write_yaml(
        tmp_path / "overlay.yaml",
        {
            "states": {
                "F-@ground": {
                    "existence": "confirmed",
                    "existence_source": "anion spectroscopy",
                    "status": "reviewed",
                    "phase": "gas",
                }
            }
        },
    )
    state = parse_state_id("F-@ground")
    assert state is not None
    record = EvidenceCatalog.load_paths((overlay,)).state(state).preferred
    assert record is not None
    assert record.existence == "confirmed"
    assert record.existence_source == "anion spectroscopy"
    assert record.reviewed


def test_reviewed_reaction_does_not_confirm_every_participant(tmp_path):
    snapshot = write_yaml(
        tmp_path / "snapshot.yaml",
        {
            "records": [
                {
                    "reaction": "e + CF4 -> F- + CF3",
                    "type": "dissociative_attachment",
                    "status": "reviewed",
                    "source": {"citation": "product spectrum"},
                }
            ]
        },
    )
    catalog = EvidenceCatalog.load_paths((snapshot,))
    assert catalog.reaction_records[0].reviewed
    assert all(record.existence == "unknown" for record in catalog.state_records)


def test_same_equation_with_another_stabilization_is_related_evidence(tmp_path):
    snapshot = write_yaml(
        tmp_path / "snapshot.yaml",
        {
            "records": [
                {
                    "reaction": "e + F -> F-",
                    "type": "attachment",
                    "stabilization": "radiative",
                    "status": "reviewed",
                }
            ]
        },
    )
    mechanical = candidates(("F",))
    channel = next(item for item in mechanical.reactions.values() if item.process == "attachment")
    catalog = EvidenceCatalog.load_paths((snapshot,))
    evidence = catalog.reaction(channel)
    assert not evidence.exact_records
    assert len(evidence.related_records) == 1
    combined = catalog.with_attested(mechanical)
    attachments = [item for item in combined.reactions.values() if item.process == "attachment"]
    assert {item.stabilization for item in attachments} == {"unspecified", "radiative"}
    assert len({item.id for item in attachments}) == 2


def test_explicit_missing_evidence_is_an_input_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        EvidenceCatalog.load_paths((tmp_path / "missing.yaml",))
    with pytest.raises(FileNotFoundError):
        EvidenceCatalog.load(tmp_path / "missing")


def test_overlay_fills_registry_null_without_erasing_negative_evidence(tmp_path):
    root = tmp_path / "registry"
    (root / "species").mkdir(parents=True)
    write_yaml(
        root / "species" / "F.yaml",
        {
            "id": "F",
            "phase": "gas",
            "composition": {"F": 1},
            "properties": {
                "mass_amu": {"value": None},
                "electron_affinity_eV": {
                    "value": None,
                    "qualifier": "unbound",
                    "evidence_tier": "reviewed",
                },
            },
        },
    )
    overlay = write_yaml(
        tmp_path / "overlay.yaml",
        {
            "properties": {
                "F@ground": {
                    "mass_amu": {"value": 18.998, "unit": "amu"},
                    "electron_affinity_eV": {"value": 3.4, "unit": "eV"},
                }
            }
        },
    )
    state = candidate_state({"F": 1}, 0, "ground")
    for paths in ((root, overlay), (overlay, root)):
        record = EvidenceCatalog.load_paths(paths).state(state).preferred
        assert record is not None
        assert record.value("mass_amu") == 18.998
        assert record.properties["electron_affinity_eV"].qualifier == "unbound"


def test_phase_and_structure_prevent_false_exact_matches():
    gas = candidate_state({"C": 2, "H": 6, "O": 1}, 0, "ground", resolution="resolved")
    ethanol = candidate_state(
        gas.composition, 0, "ground", resolution="resolved", structure="ethanol"
    )
    solid = candidate_state(gas.composition, 0, "ground", resolution="resolved", phase="solid")
    assert parse_state_id(ethanol.id).key == ethanol.key
    assert parse_state_id(solid.id).key == solid.key
    catalog = EvidenceCatalog(state_records=(StateRecord("ethanol", ethanol),))
    assert catalog.state(gas).match == "compatible"
    assert EvidenceCatalog(state_records=(StateRecord("solid", solid),)).state(gas).match == "none"


def test_declared_checksum_failure_survives_serialization_and_adoption(tmp_path):
    asset = tmp_path / "table.csv"
    asset.write_text("x,y\n1,2\n2,3\n", encoding="utf-8")
    dataset = normalized_dataset(
        {
            "id": "measured",
            "kind": "cross_section",
            "form": "table",
            "unit": "m2",
            "asset": {"path": asset.name, "sha256": "bad-declaration"},
        },
        base=tmp_path,
    )
    assert dataset.asset is not None
    assert not dataset.asset.integrity_ok
    payload = dataset_payload(dataset)
    reloaded = normalized_dataset(payload, base=tmp_path)
    assert reloaded.asset is not None
    assert not reloaded.asset.integrity_ok
    assert reloaded.asset.declared_sha256 == "bad-declaration"

    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    registry = Registry.load(root)
    reaction = next(
        item for group in registry.channels.values() for item in group if item.type == "elastic"
    )
    canonical = registry_reaction_candidate(reaction, registry.species)
    assert canonical is not None
    overlay = write_yaml(tmp_path / "overlay.yaml", {"datasets": {canonical.id: [payload]}})
    adopt.adopt(overlay, root)
    adopted = next(
        item
        for group in Registry.load(root).channels.values()
        for item in group
        if item.type == "elastic"
    ).datasets[0]
    assert adopted.asset is not None
    assert adopted.asset.available
    assert adopted.asset.declared_sha256 == "bad-declaration"
    assert not adopted.asset.integrity_ok


def test_known_additions_obey_combined_limits_and_record_the_scope(tmp_path):
    snapshot = write_yaml(
        tmp_path / "snapshot.yaml",
        {
            "records": [
                {"reaction": "e + Ar -> e + Ar + Ar", "type": "attested", "status": "imported"}
            ]
        },
    )
    mechanical = candidates(("Ar",))
    mechanical.limits["max_reactions"] = len(mechanical.reactions)
    result = EvidenceCatalog.load_paths((snapshot,)).with_attested(mechanical)
    assert len(result.reactions) <= result.limits["max_reactions"]
    assert result.completion == {"mechanical": True, "attested": False}
    assert not result.complete
    assert set(result.states) == set(mechanical.states)


def test_total_process_records_do_not_add_product_channels(tmp_path):
    snapshot = write_yaml(
        tmp_path / "snapshot.yaml",
        {
            "records": [
                {"reaction": "e + Ar -> e + Ar", "type": "excitation", "channel_scope": "total"}
            ]
        },
    )
    mechanical = candidates(("Ar",))
    result = EvidenceCatalog.load_paths((snapshot,)).with_attested(mechanical)
    assert set(result.reactions) == set(mechanical.reactions)


def test_nasa_boundary_does_not_invent_or_accept_bad_temperature_ranges():
    fit = {"low": [0.0] * 7, "high": [0.0] * 7, "t_min": 200.0, "t_mid": 1000.0, "t_max": 5000.0}
    assert normalized_thermo(fit).phase is None
    with pytest.raises(ValueError, match="finite"):
        normalized_thermo(fit | {"t_min": float("nan")})
    with pytest.raises(ValueError, match="t_min"):
        normalized_thermo(fit | {"t_max": 100.0})


def test_excitation_only_carries_mass_not_electronic_transport_response():
    registry = Registry.load(FIXTURE)
    properties = derive.carried_from(registry.species["Ar"], 11.6)
    assert "mass_amu" in properties
    assert "polarizability_A3" not in properties
    assert "collision_radius_A" not in properties
    assert properties["mass_amu"].tier == "derived"


def test_formation_offset_converts_units_and_requires_reviewed_parent_value():
    parent = Registry.load(FIXTURE).species["Ar"]
    parent = replace(
        parent,
        properties={
            "enthalpy_formation_eV": Property(
                value=96.4853321233,
                unit="kJ/mol",
                tier="reviewed",
                formation_reference=FormationReference(0, "standard_elements", 100000),
            )
        },
    )
    properties = derive.carried_from(parent, 2.0)
    assert properties["enthalpy_formation_eV"].value == pytest.approx(3.0)
    parent = replace(
        parent,
        properties={"enthalpy_formation_eV": Property(value=1.0, unit="eV", tier="imported")},
    )
    assert "enthalpy_formation_eV" not in derive.carried_from(parent, 2.0)


def test_conflicting_reviewed_and_curated_existence_does_not_change_identity():
    state = parse_state_id("F-@ground")
    assert state is not None
    positive = StateRecord(
        "positive", state, existence="confirmed", existence_source="spectroscopy", tier="curated"
    )
    negative = StateRecord(
        "negative", state, existence="unbound", existence_source="measurement", tier="reviewed"
    )
    evidence = EvidenceCatalog(state_records=(positive, negative)).state(state)
    assert evidence.match == "exact"
    assert (
        assess_state(state, evidence, CandidateSet(states={state.id: state})).verdict == "unknown"
    )


def test_invalid_existence_and_nonfinite_property_are_not_known():
    with pytest.raises(ValueError, match="existence"):
        RegistryState(existence="invalid")
    with pytest.raises(ValueError, match="existence_source"):
        RegistryState(existence="confirmed", existence_source="")
    assert not Property(float("nan"), "eV").known
    assert not Property(float("inf"), "eV").known


def test_adoption_does_not_upgrade_state_quality_or_erase_qualified_negative(tmp_path):
    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    path = root / "species" / "F.yaml"
    original = yaml.safe_load(path.read_text(encoding="utf-8"))
    original["metadata"] = {"status": "reviewed"}
    original["properties"]["electron_affinity_eV"] = {
        "value": None,
        "qualifier": "unbound",
        "evidence_tier": "reviewed",
    }
    write_yaml(path, original)
    overlay = write_yaml(
        tmp_path / "overlay.yaml",
        {
            "states": {
                "F@ground": {
                    "existence": "confirmed",
                    "existence_source": "unreviewed import",
                    "status": "imported",
                }
            },
            "properties": {"F@ground": {"electron_affinity_eV": {"value": 3.4, "unit": "eV"}}},
        },
    )
    adopt.adopt(overlay, root)
    records = EvidenceCatalog.load(root).state(parse_state_id("F@ground")).records
    incoming = next(record for record in records if record.existence == "confirmed")
    assert not incoming.reviewed
    assert incoming.properties["electron_affinity_eV"].value == 3.4
    assert incoming.properties["electron_affinity_eV"].tier == "imported"
    retained = next(
        record
        for record in records
        if record.properties.get("electron_affinity_eV")
        and record.properties["electron_affinity_eV"].qualifier == "unbound"
    )
    assert retained.properties["electron_affinity_eV"].tier == "reviewed"


def saved_analysis(tmp_path, gas, records=()):
    path = write_yaml(tmp_path / "known.yaml", {"records": list(records)})
    result = analyze(Case("boundary", (gas,)), EvidenceCatalog.load_paths((path,)))
    out = tmp_path / "analysis"
    export.write(out, result)
    return out, result


@pytest.mark.parametrize("use_id", [False, True])
@pytest.mark.parametrize("declared", [None, "unspecified", "radiative", "third_body"])
def test_ingest_matches_stabilization_at_both_entry_points(tmp_path, use_id, declared):
    known = [{"reaction": "e + F -> F-", "type": "attachment", "stabilization": "radiative"}]
    out, result = saved_analysis(tmp_path, "F", known)
    channel = next(
        r
        for r in result.candidates.reactions.values()
        if r.process == "attachment" and r.stabilization == "radiative"
    )
    record = {
        "type": "attachment",
        "kind": "rate_coefficient",
        "form": "constant",
        "parameters": {"value": 1e-15},
        "unit": "m3/s",
    }
    if use_id:
        record["reaction_id"] = channel.id
    else:
        record["reaction"] = "e + F -> F-"
    if declared is not None:
        record["stabilization"] = declared
    path = write_yaml(tmp_path / "snapshot.yaml", {"records": [record]})
    overlay = tmp_path / "overlay.yaml"
    report = ingest.ingest(path, out, overlay)
    expected = (declared == "radiative") if use_id else (declared != "third_body")
    assert report.accepted == expected
    if report.accepted:
        loaded = EvidenceCatalog.load_paths((overlay,))
        target = (
            channel
            if declared == "radiative"
            else next(
                r
                for r in result.candidates.reactions.values()
                if r.process == "attachment" and r.stabilization == "unspecified"
            )
        )
        assert len(loaded.reaction(target).overlay_datasets) == 1
        other = next(
            r
            for r in result.candidates.reactions.values()
            if r.process == "attachment" and r.id != target.id
        )
        assert not loaded.reaction(other).overlay_datasets
    else:
        assert report.review


def test_source_adapter_phase_quality_and_absence_of_existence_promotion_round_trip(tmp_path):
    out, _ = saved_analysis(tmp_path, "Ar")
    levels = asd.records([asd.Levels("Ar", lowest_eV=11.55)], "NIST ASD")
    estimated = additivity.records([additivity.Estimate("Ar", 1.5, 20)], "CCCBDB fit")
    path = snapshot.write(tmp_path / "acquired", "state_property", {}, levels + estimated)
    direct = EvidenceCatalog.load_paths((path,)).state(parse_state_id("Ar@ground"))
    properties = {
        name: prop for record in direct.records for name, prop in record.properties.items()
    }
    assert properties["polarizability_A3"].tier == "estimated"
    assert properties["lowest_excitation_energy_eV"].tier == "imported"
    assert "excitation_energy_eV" not in properties
    assert all(record.existence == "unknown" for record in direct.records)
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(path, out, overlay).accepted == 2
    placed = EvidenceCatalog.load_paths((overlay,)).state(parse_state_id("Ar@ground"))
    properties = {
        name: prop for record in placed.records for name, prop in record.properties.items()
    }
    assert properties["polarizability_A3"].tier == "estimated"
    assert properties["lowest_excitation_energy_eV"].tier == "imported"
    assert "excitation_energy_eV" not in properties
    assert all(record.existence == "unknown" for record in placed.records)


@pytest.mark.parametrize("phase", [None, "unknown", "solid"])
def test_unknown_source_phase_stays_unmatched_in_ingest(tmp_path, phase):
    out, _ = saved_analysis(tmp_path, "Ar")
    record = {
        "species": "Ar",
        "property": "polarizability_A3",
        "value": 1.5,
        "unit": "A3",
        "quality": "estimated",
    }
    if phase is not None:
        record["phase"] = phase
    path = write_yaml(tmp_path / "source.yaml", {"records": [record]})
    report = ingest.ingest(path, out, tmp_path / "overlay.yaml")
    assert report.accepted == 0
    assert len(report.review) == 1


def prepared_adoption(tmp_path, missing_asset=False):
    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    registry = Registry.load(root)
    reactions = [
        r
        for group in registry.channels.values()
        for r in group
        if r.type in {"elastic", "ionization"}
    ]
    dataset_targets = [registry_reaction_candidate(r, registry.species) for r in reactions[:2]]
    asset = tmp_path / "curve.csv"
    asset.write_text("energy_eV,cross_section_m2\n1,1e-20\n2,2e-20\n", encoding="utf-8")
    datasets = {
        c.id: [
            {
                "id": f"source-{i}",
                "kind": "cross_section",
                "form": "table",
                "unit": "m2",
                "asset": {"path": "missing.csv" if missing_asset else asset.name},
                "tier": "estimated",
                "status": "imported",
            }
        ]
        for i, c in enumerate(dataset_targets)
    }
    overlay = write_yaml(
        tmp_path / "overlay.yaml",
        {
            "properties": {
                "F@ground": {
                    "polarizability_A3": {"value": 0.6, "unit": "A3", "evidence_tier": "estimated"}
                },
                "F2@ground": {"mass_amu": {"value": 37.996, "unit": "amu"}},
            },
            "datasets": datasets,
        },
    )
    return root, overlay


def registry_bytes(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("dry_run", [False, True])
def test_missing_asset_preflight_keeps_registry_unchanged(tmp_path, dry_run):
    root, overlay = prepared_adoption(tmp_path, missing_asset=True)
    before = registry_bytes(root)
    with pytest.raises(ValueError, match="asset not found"):
        adopt.adopt(overlay, root, dry_run=dry_run)
    assert registry_bytes(root) == before
    assert not list(tmp_path.glob(".adopt-*"))


def test_invalid_state_declaration_is_rejected_before_adoption(tmp_path):
    root, overlay = prepared_adoption(tmp_path)
    document = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    document["states"] = {
        "F@ground": {"existence": "invalid", "existence_source": "unreviewed declaration"}
    }
    write_yaml(overlay, document)
    before = registry_bytes(root)
    with pytest.raises(ValueError, match="existence assertion"):
        adopt.adopt(overlay, root)
    assert registry_bytes(root) == before


def test_reviewed_null_is_a_gap_rather_than_a_negative_property_assertion(tmp_path):
    root, overlay = prepared_adoption(tmp_path)
    path = root / "species" / "F.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["properties"]["polarizability_A3"] = {"value": None, "status": "reviewed"}
    write_yaml(path, document)
    adopt.adopt(overlay, root)
    species = Registry.load(root).species["F"]
    assert species.properties["polarizability_A3"].value is None
    prop = species.records[0].properties["polarizability_A3"]
    assert prop.value == 0.6
    assert prop.tier == "estimated"
    assert prop.qualifier is None


@pytest.mark.parametrize("failure", ["stage", "replace"])
def test_adoption_save_failure_restores_files_and_removes_new_assets(
    tmp_path, monkeypatch, failure
):
    root, overlay = prepared_adoption(tmp_path)
    before = registry_bytes(root)
    if failure == "stage":
        original = Path.write_bytes

        def write_fail(path, content):
            if path.suffix == ".new":
                raise OSError("injected stage failure")
            return original(path, content)

        monkeypatch.setattr(Path, "write_bytes", write_fail)
    else:
        original_replace = adopt.os.replace
        replacements = 0

        def replace_fail(source, target):
            nonlocal replacements
            if str(source).endswith(".new"):
                replacements += 1
                if replacements == 4:
                    raise OSError("injected replacement failure")
            return original_replace(source, target)

        monkeypatch.setattr(adopt.os, "replace", replace_fail)
    with pytest.raises(OSError, match="injected"):
        adopt.adopt(overlay, root)
    assert registry_bytes(root) == before
    assert not (root / "assets").exists()
    assert not list(tmp_path.glob(".adopt-*"))


def test_successful_adoption_retains_multiple_channel_updates_and_quality(tmp_path):
    root, overlay = prepared_adoption(tmp_path)
    before = registry_bytes(root)
    report = adopt.adopt(overlay, root, dry_run=True)
    assert report.values == 4
    assert registry_bytes(root) == before
    report = adopt.adopt(overlay, root)
    assert report.values == 4
    adopted = Registry.load(root)
    data = [d for group in adopted.channels.values() for r in group for d in r.datasets]
    additions = [d for d in data if d.id.startswith("source-")]
    assert len(additions) == 2
    assert all(d.tier == "estimated" and d.status == "imported" for d in additions)
    assert all(d.asset is not None and d.asset.available for d in additions)
    assert len(list((root / "assets" / "adopted").glob("*.csv"))) == 1


def test_adoption_rollback_failure_preserves_recovery_files(tmp_path, monkeypatch):
    root, overlay = prepared_adoption(tmp_path)
    original_replace = adopt.os.replace
    replacements = 0

    def replace_fail(source, target):
        nonlocal replacements
        if str(source).endswith(".new"):
            replacements += 1
            if replacements == 4:
                raise OSError("save failed")
        if str(source).endswith(".restore"):
            raise OSError("restore failed")
        return original_replace(source, target)

    monkeypatch.setattr(adopt.os, "replace", replace_fail)
    with pytest.raises(adopt.AdoptionRecoveryError, match="recovery files") as error:
        adopt.adopt(overlay, root)
    assert isinstance(error.value.__cause__, ExceptionGroup)
    assert len(error.value.__cause__.exceptions) >= 2
    recovery = list(tmp_path.glob(".adopt-*/recovery.yaml"))
    assert len(recovery) == 1
    manifest = yaml.safe_load(recovery[0].read_text(encoding="utf-8"))
    assert manifest["registry"] == str(root)
    assert all(
        (recovery[0].parent / item["original"]).is_file()
        for item in manifest["files"]
        if item["original"]
    )


def energy_registry(tmp_path, tier="imported"):
    """Synthetic resolved level: identity assertions do not review its energy."""
    root = tmp_path / "registry"
    (root / "species").mkdir(parents=True)
    write_yaml(
        root / "species" / "Ar.yaml",
        {
            "id": "Ar",
            "composition": {"Ar": 1},
            "phase": "gas",
            "properties": {
                "ionization_energy_eV": {"value": 15.0, "unit": "eV", "quality": "reviewed"},
                "enthalpy_formation_eV": {
                    "value": 0.0,
                    "unit": "eV",
                    "quality": "reviewed",
                    "formation_reference": {
                        "temperature_K": 0,
                        "basis": "standard_elements",
                        "standard_pressure_Pa": 100000,
                    },
                },
            },
        },
    )
    write_yaml(
        root / "species" / "Ar_level.yaml",
        {
            "id": "Ar_level",
            "composition": {"Ar": 1},
            "phase": "gas",
            "metadata": {"status": tier},
            "state": {
                "kind": "resolved",
                "label": "auditlevel",
                "resolution": "resolved",
                "excitation_energy_eV": 20.0,
            },
        },
    )
    overlay = write_yaml(
        tmp_path / "existence.yaml",
        {
            "states": {
                "Ar@auditlevel": {
                    "existence": "confirmed",
                    "existence_source": "synthetic identity assertion only",
                    "status": "reviewed",
                    "phase": "gas",
                }
            }
        },
    )
    channels = write_yaml(
        tmp_path / "channels.yaml",
        {
            "records": [
                {"reaction": "e + Ar -> e + Ar@auditlevel", "type": "excitation"},
                {
                    "reaction": "Ar@auditlevel + Ar -> Ar + Ar+ + e",
                    "type": "penning_ionization",
                },
            ]
        },
    )
    return root, overlay, channels


@pytest.mark.parametrize("tier", ["imported", "reviewed"])
def test_existence_only_overlay_and_adoption_preserve_energy_qualification(tmp_path, tier):
    root, overlay, channels = energy_registry(tmp_path, tier)
    state = parse_state_id("Ar@auditlevel")
    assert state is not None
    before_derived = derive.overlay(Registry.load(root))
    for catalog in (
        EvidenceCatalog.load(root, overlay=overlay),
        EvidenceCatalog.load_paths((root, overlay)),
        EvidenceCatalog.load_paths((overlay, root)),
    ):
        energies = [
            record.properties["excitation_energy_eV"]
            for record in catalog.state(state).records
            if "excitation_energy_eV" in record.properties
        ]
        assert energies
        assert all(prop.tier == tier for prop in energies)
    source = EvidenceCatalog.load_paths((root, overlay, channels))
    result = analyze(Case("energy assertion boundary", ("Ar",), Conditions()), source)
    penning = next(
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.process == "penning_ionization" and state.id in reaction.equation
    )
    available = result.evaluation.thermochemistry.get(penning.id, {}).get(
        "penning_available_energy_eV"
    )
    assert available == (5.0 if tier == "reviewed" else None)
    export.write(tmp_path / "result", result)
    saved = export.read(tmp_path / "result", verify_views=True)
    saved_state = next(item for item in saved["states"] if item["id"] == state.id)
    energies = [
        item["properties"]["excitation_energy_eV"]
        for item in saved_state["evidence"]["records"]
        if "excitation_energy_eV" in item["properties"]
    ]
    assert all(prop["tier"] == tier and prop["unit"] == "eV" for prop in energies)
    adopt.adopt(overlay, root)
    after = Registry.load(root)
    energy = after.species["Ar_level"].properties["excitation_energy_eV"]
    assert energy.tier == tier
    assert energy.source == "registry:Ar_level"
    assert derive.overlay(after) == before_derived
    assert ("enthalpy_formation_eV" in before_derived["properties"].get(state.id, {})) == (
        tier == "reviewed"
    )
    after_result = analyze(
        Case("energy assertion boundary", ("Ar",)), EvidenceCatalog.load_paths((root, channels))
    )
    assert (
        after_result.evaluation.thermochemistry.get(penning.id, {}).get(
            "penning_available_energy_eV"
        )
        == available
    )


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_explicit_excitation_property_without_scalar_rejects_invalid_energy(value):
    state = parse_state_id("Ar@level")
    assert state is not None
    with pytest.raises(ValueError, match="finite and nonnegative"):
        StateRecord("energy", state, properties={"excitation_energy_eV": Property(value, "eV")})


def test_existence_only_adoption_handles_an_absent_property_mapping(tmp_path):
    root, overlay, _ = energy_registry(tmp_path)
    path = root / "species" / "Ar_level.yaml"
    declaration = yaml.safe_load(path.read_text(encoding="utf-8"))
    declaration["properties"] = None
    write_yaml(path, declaration)
    adopt.adopt(overlay, root)
    energy = Registry.load(root).species["Ar_level"].properties["excitation_energy_eV"]
    assert energy.tier == "imported"
    assert energy.value == 20.0


def test_excitation_duplicate_declaration_converts_units_and_rejects_disagreement():
    state = parse_state_id("Ar@level")
    assert state is not None
    prop = Property(96.4853321233, "kJ/mol", "energy source", tier="estimated")
    record = StateRecord("energy", state, energy_eV=1.0, properties={"excitation_energy_eV": prop})
    assert record.properties["excitation_energy_eV"] == prop
    assert replace(record, tier="reviewed").properties["excitation_energy_eV"].tier == "estimated"
    with pytest.raises(ValueError, match="disagree"):
        replace(record, energy_eV=2.0)


def test_scalar_snapshot_energy_preserves_independent_quality(tmp_path):
    source = write_yaml(
        tmp_path / "scalar.yaml",
        {
            "records": [
                {
                    "species": "Ar@level",
                    "phase": "gas",
                    "excitation_energy_eV": 1.0,
                    "quality": "estimated",
                    "status": "reviewed",
                    "source": {"citation": "computed energy"},
                }
            ]
        },
    )
    energy = (
        EvidenceCatalog.load_paths((source,)).state_records[0].properties["excitation_energy_eV"]
    )
    assert energy.tier == "estimated"
    assert energy.source == "computed energy"


@pytest.mark.parametrize("value", [20.0, 21.0])
def test_energy_conflict_uses_energy_quality_and_is_independent_of_overlay_order(tmp_path, value):
    root, _, _ = energy_registry(tmp_path, "reviewed")
    energy = write_yaml(
        tmp_path / "energy.yaml",
        {
            "properties": {
                "Ar@auditlevel": {
                    "excitation_energy_eV": {
                        "value": value * 96.4853321233,
                        "unit": "kJ/mol",
                        "quality": "reviewed",
                        "source": "another energy determination",
                    }
                }
            }
        },
    )
    state = parse_state_id("Ar@auditlevel")
    assert state is not None
    for catalog in (
        EvidenceCatalog.load(root, overlay=energy),
        EvidenceCatalog.load_paths((root, energy)),
        EvidenceCatalog.load_paths((energy, root)),
    ):
        matched = catalog.state(state)
        assert matched.match == "exact"
        # A disagreement in an energy declaration cannot make an identified
        # physical target ambiguous or discard either source's quantity.
        values = [
            record.properties["excitation_energy_eV"].value
            for record in matched.records
            if "excitation_energy_eV" in record.properties
        ]
        assert 20.0 in values
        assert value * 96.4853321233 in values


def test_unknown_excitation_unit_does_not_produce_an_energy_calculation(tmp_path):
    root, _, channels = energy_registry(tmp_path)
    path = root / "species" / "Ar_level.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    del document["state"]["excitation_energy_eV"]
    document["properties"] = {
        "excitation_energy_eV": {"value": 20.0, "unit": "unrecognized", "quality": "reviewed"}
    }
    write_yaml(path, document)
    result = analyze(
        Case("unknown energy unit", ("Ar",)), EvidenceCatalog.load_paths((root, channels))
    )
    assert all(
        "penning_available_energy_eV" not in values
        for values in result.evaluation.thermochemistry.values()
    )
    assert "enthalpy_formation_eV" not in derive.overlay(Registry.load(root))["properties"].get(
        "Ar@auditlevel", {}
    )


def test_reviewed_energy_remains_usable_alongside_an_unreviewed_legacy_scalar(tmp_path):
    root, existence, channels = energy_registry(tmp_path)
    observation = write_yaml(
        tmp_path / "energy_observation.yaml",
        {
            "records": [
                {
                    "species": "Ar@auditlevel",
                    "phase": "gas",
                    "property": "excitation_energy_eV",
                    "value": 21.0,
                    "unit": "eV",
                    "status": "reviewed",
                    "source": {"citation": "independent energy determination"},
                }
            ]
        },
    )
    for catalog in (
        EvidenceCatalog.load(root, overlay=existence, known=(channels, observation)),
        EvidenceCatalog.load_paths((root, existence, channels, observation)),
    ):
        result = analyze(Case("independent energy", ("Ar",)), catalog)
        penning = next(
            reaction
            for reaction in result.candidates.reactions.values()
            if reaction.process == "penning_ionization" and "Ar@auditlevel" in reaction.equation
        )
        assert result.evaluation.thermochemistry[penning.id]["penning_available_energy_eV"] == 6.0


def test_absolute_energy_uncertainty_uses_parent_unit_without_mutating_source():
    declaration = {
        "value": 2.0,
        "unit": "eV",
        "uncertainty": {"absolute": 96.4853321233, "unit": "kJ/mol", "note": "source note"},
    }
    prop = normalized_property(declaration)
    assert prop.uncertainty is not None
    assert prop.uncertainty.absolute == pytest.approx(1.0)
    assert prop.uncertainty.bounds(prop.value) == pytest.approx((1.0, 3.0))
    assert prop.uncertainty.note.startswith("source note;")
    assert "96.4853321233 kJ/mol converted to" in prop.uncertainty.note
    reloaded = normalized_property(asdict(prop))
    assert reloaded == prop
    assert declaration["uncertainty"]["unit"] == "kJ/mol"
    assert declaration["uncertainty"]["absolute"] == 96.4853321233


def test_converted_absolute_uncertainty_provenance_survives_result_round_trip(tmp_path):
    out, _ = saved_analysis(
        tmp_path,
        "Ar",
        [
            {
                "species": "Ar@ground",
                "phase": "gas",
                "property": "ionization_energy_eV",
                "value": 2.0,
                "unit": "eV",
                "uncertainty": {
                    "absolute": 96.4853321233,
                    "unit": "kJ/mol",
                    "note": "original measurement note",
                },
            }
        ],
    )
    saved = export.read(out, verify_views=True)
    state = next(item for item in saved["states"] if item["id"] == "Ar@ground")
    uncertainty = next(
        record["properties"]["ionization_energy_eV"]["uncertainty"]
        for record in state["evidence"]["records"]
        if "ionization_energy_eV" in record["properties"]
    )
    assert uncertainty["absolute"] == pytest.approx(1.0)
    assert uncertainty["note"].startswith("original measurement note;")
    assert "96.4853321233 kJ/mol converted to" in uncertainty["note"]


@pytest.mark.parametrize("dataset", [False, True])
def test_absolute_uncertainty_rejects_unsupported_unit_mismatch(dataset):
    declaration = {"value": 2.0, "unit": "m2", "uncertainty": {"absolute": 1.0, "unit": "cm2"}}
    normalize = normalized_dataset if dataset else normalized_property
    with pytest.raises(ValueError, match="uncertainty unit"):
        normalize(declaration)
    declaration["uncertainty"]["unit"] = "m2"
    assert normalize(declaration).uncertainty.absolute == 1.0


@pytest.mark.parametrize("identity", [{"phase": "solid"}, {"structure": "other-isomer"}])
@pytest.mark.parametrize("dry_run", [False, True])
def test_adoption_uses_normalized_physical_identity_for_existence_and_values(
    tmp_path, identity, dry_run
):
    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    path = write_yaml(
        tmp_path / "overlay.yaml",
        {
            "states": {
                "F@ground": {
                    **identity,
                    "existence": "confirmed",
                    "existence_source": "evidence for another physical target",
                    "status": "reviewed",
                }
            },
            "properties": {"F@ground": {"polarizability_A3": {"value": 1, "unit": "A3"}}},
        },
    )
    normalized = EvidenceCatalog.load(None, overlay=path).state_records[0]
    gas = parse_state_id("F@ground")
    assert normalized.candidate.key != gas.key
    before = registry_bytes(root)
    report = adopt.adopt(path, root, dry_run=dry_run)
    assert report.unplaced == ["F@ground"]
    assert report.written == {}
    assert registry_bytes(root) == before


@pytest.mark.parametrize("section", ["properties", "thermo"])
@pytest.mark.parametrize(
    "target",
    ["F@ground;phase=solid", "F@ground;structure=other", "F@electronic", "unknown-target"],
)
def test_adoption_without_existence_payload_still_requires_the_complete_identity(
    tmp_path, section, target
):
    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    value = (
        {"polarizability_A3": {"value": 1, "unit": "A3"}}
        if section == "properties"
        else {
            "low": [2.5, 0, 0, 0, 0, 0, 0],
            "high": [2.5, 0, 0, 0, 0, 0, 0],
            "t_min": 200,
            "t_mid": 300,
            "t_max": 1000,
            "phase": "gas",
        }
    )
    path = write_yaml(tmp_path / "overlay.yaml", {section: {target: value}})
    before = registry_bytes(root)
    report = adopt.adopt(path, root)
    assert report.unplaced == [target]
    assert registry_bytes(root) == before


def test_adoption_cannot_choose_one_registry_alias_for_an_ambiguous_physical_identity(tmp_path):
    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    duplicate = yaml.safe_load((root / "species" / "F.yaml").read_text())
    duplicate["id"] = "F-alternative"
    write_yaml(root / "species" / "alternative.yaml", duplicate)
    path = write_yaml(
        tmp_path / "overlay.yaml",
        {"properties": {"F@ground": {"polarizability_A3": {"value": 1, "unit": "A3"}}}},
    )
    before = registry_bytes(root)
    report = adopt.adopt(path, root)
    assert report.unplaced == ["F@ground"]
    assert registry_bytes(root) == before


@pytest.mark.parametrize("target", ["F", "F@ground"])
def test_ground_formula_alias_and_canonical_target_have_the_same_adoption(tmp_path, target):
    root = tmp_path / "registry"
    shutil.copytree(FIXTURE, root)
    value = {"value": 0.7, "unit": "A3", "evidence_tier": "estimated", "source": "test"}
    path = write_yaml(
        tmp_path / "overlay.yaml", {"properties": {target: {"polarizability_A3": value}}}
    )
    report = adopt.adopt(path, root)
    assert report.unplaced == []
    record = Registry.load(root).species["F"].records[0].properties["polarizability_A3"]
    assert record.value == 0.7
    assert record.tier == "estimated"


@pytest.mark.parametrize(
    "changes",
    [
        {"reaction_order": "nonnumeric"},
        {"reaction_order": True},
        {"reference_temperature_K": "room temperature"},
        {"preferred": "false"},
        {"preferred": 1},
        {"parameters": {"value": "nonnumeric"}},
        {"parameters": {"value": True}},
        {"parameters": []},
        {"validity": {"minimum": "nonnumeric", "maximum": 500}},
        {"validity": {"minimum": True, "maximum": 500}},
        {"validity": []},
        {"uncertainty": {"relative": "unspecified"}},
        {"uncertainty": False},
    ],
)
def test_malformed_numeric_declarations_are_not_reinterpreted_as_missing_or_selection(changes):
    with pytest.raises(ValueError, match="numeric|mapping|boolean|minimum|finite"):
        normalized_dataset({"form": "constant", "parameters": {"value": 1}, **changes})


def test_numeric_text_is_normalized_only_at_the_external_boundary_and_source_units_survive():
    dataset = normalized_dataset(
        {
            "form": "constant",
            "parameters": {"value": "1.5e-9", "source_unit": "cm3/s"},
            "reaction_order": "2",
            "reference_temperature_K": "300",
            "validity": {"minimum": "200", "maximum": None},
            "preferred": False,
        }
    )
    assert dataset.params == {"value": 1.5e-9}
    assert dataset.reaction_order == 2
    assert dataset.reference_temperature_K == 300
    assert dataset.validity.minimum == 200
    assert dataset.validity.maximum is None
    assert dataset.parameter_units == {"source_value": "cm3/s"}
    assert normalized_dataset(dataset_payload(dataset)) == dataset


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: NumericDataset("test", "rate_coefficient", "constant", preferred="false"),
        lambda: NumericDataset("test", "rate_coefficient", "constant", reaction_order="2"),
        lambda: NumericDataset("test", "rate_coefficient", "constant", params={"value": True}),
        lambda: NumericDataset("test", "rate_coefficient", "constant", params={"value": "1"}),
        lambda: Validity("gas_temperature", minimum="300"),
        lambda: Validity("gas_temperature", minimum=True),
        lambda: Property(True, "eV"),
    ],
)
def test_internal_numeric_records_do_not_accept_unvalidated_types(constructor):
    with pytest.raises(ValueError, match="number|boolean"):
        constructor()


def test_adoption_preserves_state_attributes_without_requalifying_an_existing_energy(tmp_path):
    root, existence, _channels = energy_registry(tmp_path)
    document = yaml.safe_load(existence.read_text())
    identity = document["states"]["Ar@auditlevel"]
    identity.update(
        configuration="synthetic configuration",
        term="synthetic term",
        J="2",
        parity="even",
        degeneracy=5,
        lifetime_s=10,
        members=["specified component"],
        excitation_energy_eV=20,
        source={"source_id": "individual level declaration"},
    )
    write_yaml(existence, document)
    report = adopt.adopt(existence, root)
    assert report.unplaced == []
    saved = Registry.load(root).species["Ar_level"]
    incoming = saved.records[0]
    assert incoming.configuration == "synthetic configuration"
    assert incoming.term == "synthetic term"
    assert incoming.j == "2"
    assert incoming.parity == "even"
    assert incoming.degeneracy == 5
    assert incoming.lifetime_s == 10
    assert incoming.members == ("specified component",)
    assert incoming.source["source_id"] == "individual level declaration"
    assert saved.properties["excitation_energy_eV"].tier == "imported"
    records = EvidenceCatalog.load(root).state(parse_state_id("Ar@auditlevel")).records
    assert any(record.configuration == incoming.configuration for record in records)
    assert any(
        record.source.get("source_id") == "individual level declaration" for record in records
    )


def test_invalid_numerical_values_remain_declared_values_without_becoming_gaps():
    dataset = normalized_dataset(
        {
            "parameters": {"value": float("nan")},
            "reaction_order": float("inf"),
            "validity": {"minimum": 500, "maximum": 300},
        }
    )
    assert dataset.params["value"] != dataset.params["value"]
    assert dataset.reaction_order == float("inf")
    assert dataset.validity.minimum == 500
    assert dataset.validity.maximum == 300
