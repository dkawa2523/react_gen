from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools import chemical_identity_fetch
from external_data_tools.chemical_identity_fetch import fetch_chemical_identity
from plasma_reactgen.data_sources.chemical_identity_snapshot import (
    ChemicalIdentitySnapshotProvider,
    enrich_species_identity_metadata,
)
from plasma_reactgen.preparation.enricher import enrich_case


def test_local_chemical_identity_snapshot_enriches_aliases_and_identifiers(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(prepared_registry, "CF4", aliases=["CF4"], composition={"C": 1, "F": 4})
    snapshot = _write_identity_snapshot(tmp_path / "chemical_identity.yaml")

    report = enrich_species_identity_metadata(
        prepared_registry,
        ChemicalIdentitySnapshotProvider(snapshot),
    )

    species = _read_yaml(prepared_registry / "species" / "CF4.yaml")
    assert report["summary"] == {"n_updated_species": 1, "n_conflicts": 0}
    assert species["metadata"]["aliases"] == ["CF4", "tetrafluoromethane", "carbon tetrafluoride"]
    assert species["metadata"]["identifiers"]["chebi_id"] == "CHEBI:38834"
    assert species["metadata"]["identifiers"]["inchikey"] == "TXEYQDLBPFQVAA-UHFFFAOYSA-N"
    assert species["metadata"]["ontology_tags"] == ["halocarbon"]


def test_existing_aliases_and_identifiers_are_preserved(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(
        prepared_registry,
        "CF4",
        aliases=["existing alias"],
        identifiers={"inchikey": "existing-inchikey"},
        composition={"C": 1, "F": 4},
    )
    snapshot = _write_identity_snapshot(tmp_path / "chemical_identity.yaml")

    enrich_species_identity_metadata(prepared_registry, ChemicalIdentitySnapshotProvider(snapshot))

    species = _read_yaml(prepared_registry / "species" / "CF4.yaml")
    assert species["metadata"]["aliases"] == [
        "existing alias",
        "tetrafluoromethane",
        "carbon tetrafluoride",
    ]
    assert species["metadata"]["identifiers"]["inchikey"] == "existing-inchikey"
    assert species["metadata"]["identifiers"]["chebi_id"] == "CHEBI:38834"


def test_conflicting_formula_and_composition_are_reported(tmp_path):
    prepared_registry = tmp_path / "prepared_registry"
    _write_species(prepared_registry, "CF4", formula="C2F6", composition={"C": 2, "F": 6})
    snapshot = _write_identity_snapshot(tmp_path / "chemical_identity.yaml")

    report = enrich_species_identity_metadata(prepared_registry, ChemicalIdentitySnapshotProvider(snapshot))

    assert {
        "kind": "formula_conflict",
        "species": "CF4",
        "existing_formula": "C2F6",
        "candidate_formula": "CF4",
        "action": "manual_review",
    } in report["conflicts"]
    assert {
        "kind": "composition_conflict",
        "species": "CF4",
        "existing_composition": {"C": 2, "F": 6},
        "candidate_composition": {"C": 1, "F": 4},
        "action": "manual_review",
    } in report["conflicts"]


def test_chemspider_skeleton_without_api_key_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("CHEMSPIDER_API_KEY", raising=False)
    species_list = _write_species_list(tmp_path / "species.yaml")

    snapshot = fetch_chemical_identity(
        species_list,
        output_root=tmp_path / "raw",
        snapshot_path=tmp_path / "snapshot.yaml",
        provider="chemspider",
    )

    assert snapshot["records"] == []
    assert snapshot["unresolved"][0]["reason"] == "chemspider_api_key_not_configured"


def test_chebi_local_snapshot_fetch_normalizes_and_records_sha256(tmp_path):
    species_list = _write_species_list(tmp_path / "species.yaml")
    chebi_local = _write_yaml(
        tmp_path / "chebi_local.yaml",
        {
            "schema_version": 1,
            "records": [
                {
                    "id": "CHEBI:38834",
                    "species": "CF4",
                    "query": "tetrafluoromethane",
                    "formula": "CF4",
                    "aliases": ["tetrafluoromethane"],
                    "ontology_tags": ["halocarbon"],
                    "inchikey": "TXEYQDLBPFQVAA-UHFFFAOYSA-N",
                }
            ],
        },
    )
    output_root = tmp_path / "raw"
    snapshot_path = tmp_path / "snapshot.yaml"

    snapshot = fetch_chemical_identity(
        species_list,
        output_root=output_root,
        snapshot_path=snapshot_path,
        provider="chebi",
        local_snapshot=chebi_local,
    )

    manifest = _read_yaml(output_root / "manifest.yaml")
    assert snapshot["records"][0]["identifiers"]["chebi_id"] == "CHEBI:38834"
    assert snapshot["records"][0]["source_records"][0]["database"] == "ChEBI"
    assert len(snapshot["records"][0]["source_records"][0]["sha256"]) == 64
    assert manifest["source_files"][0]["raw_file"].endswith("chebi_local.yaml")
    assert len(manifest["source_files"][0]["sha256"]) == 64


def test_identity_fetch_dry_run_does_not_call_network_or_write_files(tmp_path, monkeypatch):
    species_list = _write_species_list(tmp_path / "species.yaml")

    def fail_download(*args, **kwargs):
        raise AssertionError("identity dry-run must not download")

    monkeypatch.setattr(chemical_identity_fetch, "download_url", fail_download, raising=False)

    result = fetch_chemical_identity(
        species_list,
        output_root=tmp_path / "raw",
        snapshot_path=tmp_path / "snapshot.yaml",
        provider="nci_cactus",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["summary"]["planned"] == 1
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "snapshot.yaml").exists()


def test_enrich_uses_chemical_identity_snapshot_when_profile_includes_it(tmp_path):
    registry_root = tmp_path / "registry"
    workspace = tmp_path / "workspace"
    case = tmp_path / "case.yaml"
    snapshot = _write_identity_snapshot(tmp_path / "external_data" / "snapshots" / "chemical_identity.yaml")
    _write_species(registry_root, "CF4", composition={"C": 1, "F": 4})
    case.write_text(
        yaml.safe_dump({"case": {"name": "identity"}, "gases": ["CF4"]}, sort_keys=False),
        encoding="utf-8",
    )

    report = enrich_case(
        case,
        registry_root,
        workspace,
        {
            "name": "identity_profile",
            "species_identity": ["local_registry", "chemical_identity_snapshot"],
            "properties": ["local_registry"],
            "chemical_identity_snapshot": {"snapshot": str(snapshot)},
        },
    )

    species = _read_yaml(workspace / "prepared_registry" / "species" / "CF4.yaml")
    assert report["summary"]["identity_species_updated"] == 1
    assert species["metadata"]["identifiers"]["chebi_id"] == "CHEBI:38834"


def _write_identity_snapshot(path: Path) -> Path:
    return _write_yaml(
        path,
        {
            "schema_version": 1,
            "source": {
                "source_type": "local_snapshot",
                "database": "chemical_identity_merged",
                "generated_at": "2026-06-15T00:00:00+00:00",
            },
            "records": [
                {
                    "species": "CF4",
                    "query": "tetrafluoromethane",
                    "identifiers": {
                        "chebi_id": "CHEBI:38834",
                        "inchikey": "TXEYQDLBPFQVAA-UHFFFAOYSA-N",
                        "canonical_smiles": "C(F)(F)(F)F",
                    },
                    "formula": "CF4",
                    "aliases": ["tetrafluoromethane", "carbon tetrafluoride"],
                    "ontology_tags": ["halocarbon"],
                    "source_records": [{"database": "ChEBI", "raw_file": "chebi.yaml"}],
                }
            ],
        },
    )


def _write_species_list(path: Path) -> Path:
    return _write_yaml(
        path,
        {"schema_version": 1, "species": [{"id": "CF4", "query": "tetrafluoromethane"}]},
    )


def _write_species(
    root: Path,
    species_id: str,
    aliases: list[str] | None = None,
    identifiers: dict | None = None,
    formula: str | None = "CF4",
    composition: dict | None = None,
) -> None:
    _write_yaml(
        root / "species" / f"{species_id}.yaml",
        {
            "schema_version": 1,
            "id": species_id,
            "formula": formula,
            "composition": composition or {},
            "charge": 0,
            "classes": ["neutral"],
            "state": {},
            "properties": {},
            "metadata": {
                "status": "prepared",
                "aliases": aliases or [],
                "identifiers": identifiers or {},
            },
        },
    )


def _write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
