from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.lxcat_raw_import import import_lxcat_raw_file, main


def test_simple_csv_imports_normalized_asset_and_metadata(tmp_path):
    raw_file = tmp_path / "cf4.csv"
    raw_file.write_text(
        "energy_eV,cross_section_m2,process,target\n"
        "2.0,2.0e-20,elastic,CF4\n"
        "0.0,0.0,elastic,CF4\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    report = import_lxcat_raw_file(raw_file, workspace=workspace, target="CF4")

    asset_path = workspace / "prepared_registry" / report["assets"][0]["asset_path"]
    metadata_path = workspace / "prepared_registry" / report["assets"][0]["metadata_path"]
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))

    assert report["summary"]["n_assets_imported"] == 1
    assert report["summary"]["n_unmapped"] == 1
    assert report["unresolved"] == []
    assert asset_path.read_text(encoding="utf-8").splitlines() == [
        "energy_eV,cross_section_m2",
        "0.0,0.0",
        "2.0,2e-20",
    ]
    assert metadata["original_file"] == str(raw_file)
    assert metadata["source"] == "lxcat_manual"
    assert metadata["target"] == "CF4"
    assert metadata["process_label_original"] == "elastic"
    assert metadata["units"] == {"energy": "eV", "cross_section": "m2"}
    assert metadata["row_count"] == 2
    assert metadata["energy_min_eV"] == 0.0
    assert metadata["energy_max_eV"] == 2.0
    assert len(metadata["sha256"]) == 64
    assert metadata["license_note"] == "User must follow LXCat citation and redistribution requirements."


def test_bolsig_like_minimal_fixture_imports(tmp_path):
    raw_file = tmp_path / "cf4_bolsig.txt"
    raw_file.write_text(
        "DISSOCIATION CF4 -> CF3 + F\n"
        "TARGET: CF4\n"
        "Energy(eV) Cross section (m2)\n"
        "12.0 0.0\n"
        "15.0 1.5e-21\n",
        encoding="utf-8",
    )

    report = import_lxcat_raw_file(
        raw_file,
        workspace=tmp_path / "workspace",
        target="CF4",
        source="lxcat_manual",
    )

    metadata_path = tmp_path / "workspace" / "prepared_registry" / report["assets"][0]["metadata_path"]
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))

    assert report["summary"]["n_assets_imported"] == 1
    assert metadata["input_format"] == "bolsig_lxcat_minimal"
    assert metadata["process_label_original"] == "DISSOCIATION CF4 -> CF3 + F"
    assert metadata["row_count"] == 2


def test_ambiguous_file_reports_unresolved_and_does_not_import(tmp_path):
    raw_file = tmp_path / "ambiguous.txt"
    raw_file.write_text(
        "First process\n"
        "Second process\n"
        "0 0\n"
        "1 1e-20\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    report = import_lxcat_raw_file(raw_file, workspace=workspace, target="CF4")

    assert report["summary"]["n_assets_imported"] == 0
    assert report["summary"]["n_unresolved"] == 1
    assert report["unresolved"][0]["reason"] == "ambiguous_or_unsupported_format"
    assert not (workspace / "prepared_registry").exists()


def test_mapping_updates_prepared_registry_only(tmp_path):
    workspace = tmp_path / "workspace"
    prepared_registry = workspace / "prepared_registry"
    registry_root = tmp_path / "registry"
    _write_prepared_reaction(prepared_registry)
    _write_yaml(
        registry_root / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "channels": [
                {
                    "id": "e_CF4_dissociation_CF3_F",
                    "data": {"cross_section": {"path": None}},
                }
            ],
        },
    )
    original_registry = {
        path: path.read_text(encoding="utf-8")
        for path in registry_root.rglob("*.yaml")
    }
    mapping_file = tmp_path / "external_data" / "lxcat" / "mappings.yaml"
    _write_yaml(
        mapping_file,
        {
            "schema_version": 1,
            "mappings": [
                {
                    "target": "CF4",
                    "process_label_contains": "dissociation",
                    "reaction_id": "e_CF4_dissociation_CF3_F",
                    "mapping_status": "manual_review_required",
                }
            ],
        },
    )
    raw_file = tmp_path / "cf4.tsv"
    raw_file.write_text(
        "energy_eV\tcross_section_m2\tprocess\ttarget\n"
        "10\t0\tDISSOCIATION\tCF4\n"
        "15\t1e-21\tDISSOCIATION\tCF4\n",
        encoding="utf-8",
    )

    report = import_lxcat_raw_file(
        raw_file,
        workspace=workspace,
        target="CF4",
        source="lxcat_manual",
        mapping_file=mapping_file,
    )

    prepared = yaml.safe_load(
        (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").read_text(
            encoding="utf-8"
        )
    )
    cross_section = prepared["channels"][0]["data"]["cross_section"]

    assert report["summary"]["n_mapped"] == 1
    assert report["unresolved"] == []
    assert cross_section["status"] == "local_file_registered"
    assert cross_section["path"] == report["assets"][0]["asset_path"]
    assert cross_section["format"] == "csv_energy_eV_sigma_m2"
    assert cross_section["source"] == "lxcat_manual"
    assert cross_section["mapping_status"] == "manual_review_required"
    assert cross_section["process_label_original"] == "DISSOCIATION"
    assert {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")} == original_registry


def test_cli_writes_import_report(tmp_path):
    raw_file = tmp_path / "cf4.csv"
    raw_file.write_text(
        "energy_eV,cross_section_m2,process,target\n"
        "0,0,elastic,CF4\n"
        "1,1e-20,elastic,CF4\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    exit_code = main(
        [
            str(raw_file),
            "--workspace",
            str(workspace),
            "--target",
            "CF4",
            "--source",
            "lxcat_manual",
        ]
    )

    report = yaml.safe_load((workspace / "lxcat_import_report.yaml").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["summary"]["n_assets_imported"] == 1
    assert report["summary"]["n_unmapped"] == 1


def test_no_network_access_is_used(tmp_path, monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("LXCat raw import must not use network access")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    raw_file = tmp_path / "cf4.csv"
    raw_file.write_text(
        "energy_eV,cross_section_m2\n"
        "0,0\n"
        "1,1e-20\n",
        encoding="utf-8",
    )

    report = import_lxcat_raw_file(raw_file, workspace=tmp_path / "workspace", target="CF4")

    assert report["summary"]["n_assets_imported"] == 1


def _write_prepared_reaction(prepared_registry: Path) -> None:
    _write_yaml(
        prepared_registry / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
            "channels": [
                {
                    "id": "e_CF4_dissociation_CF3_F",
                    "type": "dissociation",
                    "products": [{"species": "e", "n": 1}, {"species": "CF3", "n": 1}],
                    "data": {"cross_section": {"path": None, "comment": "keep me"}},
                }
            ],
        },
    )


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
