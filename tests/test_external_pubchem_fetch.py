from __future__ import annotations

from pathlib import Path
import json

import pytest
import yaml

from external_data_tools import pubchem_fetch


def test_pubchem_fetch_writes_normalized_snapshot(tmp_path, monkeypatch):
    species_list = _write_species_list(
        tmp_path,
        [{"id": "CF4", "query": "tetrafluoromethane"}],
    )
    output_root = tmp_path / "raw" / "pubchem"
    snapshot_path = tmp_path / "snapshots" / "pubchem_species.yaml"

    def fake_download_url(url, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(_payload_for_url(url)),
            encoding="utf-8",
        )
        return {"url": url, "output_path": str(output_path), "sha256": "fake"}

    monkeypatch.setattr(pubchem_fetch, "download_url", fake_download_url)

    snapshot = pubchem_fetch.fetch_pubchem_snapshot(
        species_list,
        output_root=output_root,
        snapshot_path=snapshot_path,
    )

    assert snapshot_path.exists()
    loaded = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
    assert loaded == snapshot
    assert loaded["source"]["database"] == "PubChem"
    assert loaded["source"]["access_mode"] == "pug_rest"
    assert loaded["unresolved"] == []

    record = loaded["records"][0]
    assert record["species"] == "CF4"
    assert record["query"] == "tetrafluoromethane"
    assert record["identifiers"] == {
        "pubchem_cid": 6393,
        "inchikey": "TXEYQDLBPFQVAA-UHFFFAOYSA-N",
        "canonical_smiles": "C(F)(F)(F)F",
        "isomeric_smiles": "C(F)(F)(F)F",
    }
    assert record["formula"] == "CF4"
    assert record["molecular_weight"] == 88.0043
    assert record["aliases"][:2] == ["tetrafluoromethane", "carbon tetrafluoride"]
    assert len(record["aliases"]) == 50
    assert record["source_record"]["source_type"] == "public_database_api_snapshot"
    assert record["source_record"]["database"] == "PubChem"
    assert record["source_record"]["citation"] == "PubChem PUG REST snapshot generated locally"
    assert len(record["source_record"]["raw_files"]) == 3
    assert all(Path(path).exists() for path in record["source_record"]["raw_files"])


def test_pubchem_fetch_dry_run_creates_no_files(tmp_path, monkeypatch):
    species_list = _write_species_list(
        tmp_path,
        [{"id": "CHF3", "query": "fluoroform"}],
    )
    output_root = tmp_path / "raw" / "pubchem"
    snapshot_path = tmp_path / "snapshots" / "pubchem_species.yaml"

    def fail_download_url(*args, **kwargs):
        raise AssertionError("dry-run should not call download_url")

    monkeypatch.setattr(pubchem_fetch, "download_url", fail_download_url)

    result = pubchem_fetch.fetch_pubchem_snapshot(
        species_list,
        output_root=output_root,
        snapshot_path=snapshot_path,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["summary"]["planned_species"] == 1
    assert result["planned"][0]["urls"]["cid_lookup"].endswith(
        "/compound/name/fluoroform/cids/JSON"
    )
    assert not output_root.exists()
    assert not snapshot_path.exists()


def test_pubchem_fetch_failed_cid_lookup_adds_unresolved(tmp_path, monkeypatch):
    species_list = _write_species_list(
        tmp_path,
        [{"id": "bad", "query": "not a cid"}],
    )
    snapshot_path = tmp_path / "snapshots" / "pubchem_species.yaml"

    def fake_download_url(url, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"IdentifierList": {"CID": []}}), encoding="utf-8")
        return {"url": url, "output_path": str(output_path), "sha256": "fake"}

    monkeypatch.setattr(pubchem_fetch, "download_url", fake_download_url)

    snapshot = pubchem_fetch.fetch_pubchem_snapshot(
        species_list,
        output_root=tmp_path / "raw" / "pubchem",
        snapshot_path=snapshot_path,
    )

    assert snapshot["records"] == []
    assert snapshot["unresolved"] == [
        {
            "species": "bad",
            "query": "not a cid",
            "stage": "cid_lookup",
            "reason": "no PubChem CID found",
            "raw_files": snapshot["unresolved"][0]["raw_files"],
        }
    ]
    assert snapshot["unresolved"][0]["raw_files"]


def test_pubchem_fetch_existing_snapshot_requires_overwrite(tmp_path, monkeypatch):
    species_list = _write_species_list(
        tmp_path,
        [{"id": "CF4", "query": "tetrafluoromethane"}],
    )
    snapshot_path = tmp_path / "snapshots" / "pubchem_species.yaml"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text("schema_version: 1\nrecords: []\n", encoding="utf-8")

    def fail_download_url(*args, **kwargs):
        raise AssertionError("download_url should not run before overwrite check")

    monkeypatch.setattr(pubchem_fetch, "download_url", fail_download_url)

    exit_code = pubchem_fetch.main(
        [
            str(species_list),
            "--output-root",
            str(tmp_path / "raw" / "pubchem"),
            "--snapshot",
            str(snapshot_path),
        ]
    )

    assert exit_code == 1


def test_pubchem_fetch_main_dry_run_returns_success(tmp_path, monkeypatch):
    species_list = _write_species_list(
        tmp_path,
        [{"id": "C2F6", "query": "hexafluoroethane"}],
    )

    def fail_download_url(*args, **kwargs):
        raise AssertionError("dry-run should not call download_url")

    monkeypatch.setattr(pubchem_fetch, "download_url", fail_download_url)

    exit_code = pubchem_fetch.main(
        [
            str(species_list),
            "--output-root",
            str(tmp_path / "raw" / "pubchem"),
            "--snapshot",
            str(tmp_path / "snapshots" / "pubchem_species.yaml"),
            "--dry-run",
        ]
    )

    assert exit_code == 0


def _write_species_list(tmp_path: Path, species: list[dict[str, str]]) -> Path:
    path = tmp_path / "species.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "species": species}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _payload_for_url(url: str) -> dict:
    if "/cids/" in url:
        return {"IdentifierList": {"CID": [6393]}}
    if "/property/" in url:
        return {
            "PropertyTable": {
                "Properties": [
                    {
                        "CID": 6393,
                        "MolecularFormula": "CF4",
                        "MolecularWeight": 88.0043,
                        "CanonicalSMILES": "C(F)(F)(F)F",
                        "IsomericSMILES": "C(F)(F)(F)F",
                        "InChIKey": "TXEYQDLBPFQVAA-UHFFFAOYSA-N",
                    }
                ]
            }
        }
    if "/synonyms/" in url:
        return {
            "InformationList": {
                "Information": [
                    {
                        "Synonym": [
                            "tetrafluoromethane",
                            "carbon tetrafluoride",
                            "tetrafluoromethane",
                        ]
                        + [f"alias-{index}" for index in range(60)]
                    }
                ]
            }
        }
    raise AssertionError(f"unexpected URL: {url}")
