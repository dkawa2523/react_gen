from pathlib import Path

import yaml

from plasma_reactgen.interface.cli import main
from plasma_reactgen.preparation.cross_section_mapping import apply_cross_section_mappings


def test_mapping_updates_prepared_registry_channel_preserving_fields(tmp_path):
    workspace = tmp_path / "workspace"
    prepared_registry = workspace / "prepared_registry"
    _make_prepared_reaction(prepared_registry)
    asset_path = _make_asset(prepared_registry, "assets/cross_sections/e_CF4_elastic.csv")
    mapping_file = _make_mapping(
        tmp_path / "mapping.yaml",
        [
            {
                "reaction_id": "e_CF4_elastic",
                "asset_path": asset_path,
                "source": "lxcat_offline",
                "mapping_status": "reviewed",
                "process_label_original": "ELASTIC",
                "notes": ["Mapped manually."],
            }
        ],
    )

    report = apply_cross_section_mappings(prepared_registry, mapping_file)

    payload = yaml.safe_load(
        (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").read_text(
            encoding="utf-8"
        )
    )
    cross_section = payload["channels"][0]["data"]["cross_section"]

    assert report["summary"]["n_updated"] == 1
    assert report["summary"]["n_unresolved"] == 0
    assert cross_section["status"] == "local_file_registered"
    assert cross_section["path"] == "assets/cross_sections/e_CF4_elastic.csv"
    assert cross_section["source"] == "lxcat_offline"
    assert cross_section["mapping_status"] == "reviewed"
    assert cross_section["process_label_original"] == "ELASTIC"
    assert cross_section["format"] == "csv_energy_eV_sigma_m2"
    assert cross_section["comment"] == "keep me"


def test_missing_reaction_is_reported(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    _make_prepared_reaction(prepared_registry)
    asset_path = _make_asset(prepared_registry, "assets/cross_sections/missing.csv")
    mapping_file = _make_mapping(
        tmp_path / "mapping.yaml",
        [{"reaction_id": "missing_reaction", "asset_path": asset_path, "source": "lxcat_offline"}],
    )

    report = apply_cross_section_mappings(prepared_registry, mapping_file)

    assert report["summary"]["n_updated"] == 0
    assert report["unresolved"] == [
        {
            "reaction_id": "missing_reaction",
            "asset_path": "assets/cross_sections/missing.csv",
            "reason": "reaction_id_not_found",
        }
    ]


def test_missing_asset_is_reported_but_matching_channel_is_updated(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    _make_prepared_reaction(prepared_registry)
    mapping_file = _make_mapping(
        tmp_path / "mapping.yaml",
        [
            {
                "reaction_id": "e_CF4_elastic",
                "asset_path": "assets/cross_sections/does_not_exist.csv",
                "source": "lxcat_offline",
                "mapping_status": "reviewed",
            }
        ],
    )

    report = apply_cross_section_mappings(prepared_registry, mapping_file)
    payload = yaml.safe_load(
        (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert report["summary"]["n_updated"] == 1
    assert report["unresolved"] == [
        {
            "reaction_id": "e_CF4_elastic",
            "asset_path": "assets/cross_sections/does_not_exist.csv",
            "reason": "asset_not_found",
        }
    ]
    assert payload["channels"][0]["data"]["cross_section"]["path"] == "assets/cross_sections/does_not_exist.csv"


def test_mapping_only_scans_electron_prepared_registry_and_registry_is_unchanged(tmp_path):
    workspace = tmp_path / "workspace"
    prepared_registry = workspace / "prepared_registry"
    registry_root = tmp_path / "registry"
    _make_prepared_reaction(prepared_registry)
    _write_yaml(
        prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml",
        {
            "schema_version": 1,
            "channels": [{"id": "ion_match", "data": {"cross_section": {"path": None}}}],
        },
    )
    _write_yaml(
        registry_root / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "channels": [{"id": "e_CF4_elastic", "data": {"cross_section": {"path": None}}}],
        },
    )
    original_registry = {
        path: path.read_text(encoding="utf-8")
        for path in registry_root.rglob("*.yaml")
    }
    _make_asset(prepared_registry, "assets/cross_sections/ion.csv")
    mapping_file = _make_mapping(
        tmp_path / "mapping.yaml",
        [{"reaction_id": "ion_match", "asset_path": "assets/cross_sections/ion.csv"}],
    )

    report = apply_cross_section_mappings(prepared_registry, mapping_file)

    assert report["summary"]["n_updated"] == 0
    assert report["unresolved"][0]["reason"] == "reaction_id_not_found"
    assert {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")} == original_registry


def test_cli_apply_cross_section_mapping(tmp_path):
    workspace = tmp_path / "workspace"
    prepared_registry = workspace / "prepared_registry"
    _make_prepared_reaction(prepared_registry)
    _make_asset(prepared_registry, "assets/cross_sections/e_CF4_elastic.csv")
    mapping_file = _make_mapping(
        tmp_path / "mapping.yaml",
        [
            {
                "reaction_id": "e_CF4_elastic",
                "asset_path": "assets/cross_sections/e_CF4_elastic.csv",
                "source": "lxcat_offline",
            }
        ],
    )

    rc = main(
        [
            "apply-cross-section-mapping",
            str(mapping_file),
            "--workspace",
            str(workspace),
        ]
    )

    payload = yaml.safe_load(
        (prepared_registry / "reactions" / "electron" / "e__CF4.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert rc == 0
    assert payload["channels"][0]["data"]["cross_section"]["path"] == "assets/cross_sections/e_CF4_elastic.csv"


def _make_prepared_reaction(prepared_registry: Path) -> None:
    _write_yaml(
        prepared_registry / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
            "channels": [
                {
                    "id": "e_CF4_elastic",
                    "type": "elastic",
                    "products": [{"species": "e", "n": 1}, {"species": "CF4", "n": 1}],
                    "data": {
                        "cross_section": {
                            "path": None,
                            "format": "csv_energy_eV_sigma_m2",
                            "comment": "keep me",
                        }
                    },
                }
            ],
        },
    )


def _make_asset(prepared_registry: Path, asset_path: str) -> str:
    path = prepared_registry / asset_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("energy_eV,cross_section_m2\n0,0\n1,1e-20\n", encoding="utf-8")
    return asset_path


def _make_mapping(path: Path, mappings: list[dict]) -> Path:
    _write_yaml(path, {"schema_version": 1, "mappings": mappings})
    return path


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
