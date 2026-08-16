from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.cache import sha256_file
from external_data_tools.openadas_raw_import import import_openadas_manifest, main


def test_openadas_raw_file_copied_and_sha256_recorded(tmp_path):
    raw_file = tmp_path / "adf07_file.dat"
    raw_file.write_text("ADF07 example\n1 2 3\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "openadas_manifest.yaml",
        [
            {
                "id": "adf07_example",
                "local_path": str(raw_file),
                "adf_class": "ADF07",
                "description": "electron impact ionisation coefficients",
                "citation": "OpenADAS example citation",
            }
        ],
    )
    workspace = tmp_path / "workspace"

    report = import_openadas_manifest(manifest, workspace=workspace)

    cached = workspace / "source_cache" / report["files"][0]["cached_path"]
    source_manifest_path = workspace / "source_cache" / "manifest.yaml"
    source_manifest = yaml.safe_load(source_manifest_path.read_text(encoding="utf-8"))
    report_path = workspace / "openadas_import_report.yaml"
    report_payload = yaml.safe_load(report_path.read_text(encoding="utf-8"))

    assert cached.exists()
    assert cached.read_text(encoding="utf-8") == raw_file.read_text(encoding="utf-8")
    assert report["files"][0]["sha256"] == sha256_file(raw_file)
    assert report["files"][0]["adf_class"] == "ADF07"
    assert report["schema_version"] == 2
    assert "registry_mutated" not in report
    assert source_manifest["source_files"][0]["id"] == "adf07_example"
    assert source_manifest["source_files"][0]["cached_path"].startswith("openadas/adf07_example/")
    assert report_payload["summary"]["n_cached"] == 1
    assert report_payload["summary"]["n_ion_reaction_tables"] == 0


def test_adf01_mapping_writes_generic_ion_reaction_table(tmp_path):
    raw_file = tmp_path / "adf01_file.dat"
    raw_file.write_text("ADF01 charge exchange\n", encoding="utf-8")
    output_table = tmp_path / "external_data" / "snapshots" / "openadas_ion_reactions.yaml"
    manifest = _write_manifest(
        tmp_path / "openadas_manifest.yaml",
        [
            {
                "id": "adf01_example",
                "local_path": str(raw_file),
                "adf_class": "ADF01",
                "description": "charge exchange cross sections",
                "citation": "OpenADAS ADF01 citation",
            }
        ],
        mappings=[
            {
                "file_id": "adf01_example",
                "projectile": "H+",
                "target": "H",
                "family": "ion_neutral",
                "type": "charge_transfer",
                "dnt_class": "long_range_charge_exchange",
                "output_table": str(output_table),
            }
        ],
    )

    report = import_openadas_manifest(manifest, workspace=tmp_path / "workspace")
    table = yaml.safe_load(output_table.read_text(encoding="utf-8"))
    reaction = table["reactions"][0]

    assert report["summary"]["n_ion_reaction_tables"] == 1
    assert table["source"]["database"] == "OpenADAS"
    assert reaction["projectile"] == "H+"
    assert reaction["target"] == "H"
    assert reaction["family"] == "ion_neutral"
    assert reaction["type"] == "charge_transfer"
    assert reaction["dnt_class"] == "long_range_charge_exchange"
    assert reaction["status"] == "imported"
    assert reaction["data"]["openadas"]["file_id"] == "adf01_example"
    assert reaction["source_record"]["database"] == "OpenADAS"


def test_unsupported_adf_class_reports_unresolved_but_records_raw_file(tmp_path):
    raw_file = tmp_path / "adf99_file.dat"
    raw_file.write_text("unsupported\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "openadas_manifest.yaml",
        [
            {
                "id": "adf99_example",
                "local_path": str(raw_file),
                "adf_class": "ADF99",
                "description": "unsupported",
            }
        ],
    )

    report = import_openadas_manifest(manifest, workspace=tmp_path / "workspace")

    assert report["summary"]["n_cached"] == 1
    assert report["summary"]["n_unresolved"] == 1
    assert report["unresolved"] == [
        {
            "id": "adf99_example",
            "adf_class": "ADF99",
            "reason": "unsupported_adf_class",
        }
    ]


def test_openadas_import_does_not_mutate_curated_registry(tmp_path):
    raw_file = tmp_path / "adf01_file.dat"
    raw_file.write_text("ADF01\n", encoding="utf-8")
    registry_root = tmp_path / "registry"
    _write_yaml(
        registry_root / "reactions" / "ion_neutral" / "H_p__H.yaml",
        {"schema_version": 1, "channels": [{"id": "curated"}]},
    )
    original_registry = {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    }
    manifest = _write_manifest(
        tmp_path / "openadas_manifest.yaml",
        [{"id": "adf01_example", "local_path": str(raw_file), "adf_class": "ADF01"}],
        mappings=[
            {
                "file_id": "adf01_example",
                "projectile": "H+",
                "target": "H",
                "family": "ion_neutral",
                "type": "charge_transfer",
                "dnt_class": "long_range_charge_exchange",
                "output_table": str(tmp_path / "external_data" / "snapshots" / "openadas.yaml"),
            }
        ],
    )

    import_openadas_manifest(manifest, workspace=tmp_path / "workspace")

    current_registry = {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    }
    assert current_registry == original_registry


def test_openadas_cli_and_no_network_access(tmp_path, monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("OpenADAS raw import must not use network access")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    raw_file = tmp_path / "adf07_file.dat"
    raw_file.write_text("ADF07\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path / "openadas_manifest.yaml",
        [{"id": "adf07_example", "local_path": str(raw_file), "adf_class": "ADF07"}],
    )
    workspace = tmp_path / "workspace"

    exit_code = main([str(manifest), "--workspace", str(workspace)])

    report = yaml.safe_load((workspace / "openadas_import_report.yaml").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["summary"]["n_cached"] == 1


def _write_manifest(path: Path, files: list[dict], mappings: list[dict] | None = None) -> Path:
    payload = {
        "schema_version": 1,
        "source": {"database": "OpenADAS", "access_mode": "manual_download"},
        "files": files,
    }
    if mappings is not None:
        payload["openadas_mappings"] = mappings
    return _write_yaml(path, payload)


def _write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path
