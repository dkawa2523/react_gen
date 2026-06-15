from pathlib import Path
import socket

import yaml

from plasma_reactgen.interface.cli import main


def test_enrich_command_works_with_local_profile_without_network(tmp_path, monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("network access should not be attempted")

    monkeypatch.setattr(socket, "socket", fail_socket)
    registry = _make_registry(tmp_path / "registry")
    case = _make_case(tmp_path / "case.yaml", ["CF4"])
    workspace = tmp_path / "workspace"
    original_registry = _snapshot_yaml(registry)

    rc = main(
        [
            "enrich",
            str(case),
            "--registry",
            str(registry),
            "--workspace",
            str(workspace),
            "--source-profile",
            "local_only",
        ]
    )

    report = _read_yaml(workspace / "enrichment_report.yaml")
    assert rc == 0
    assert (workspace / "prepared_registry" / "species" / "CF4.yaml").exists()
    assert (workspace / "prepared_registry" / "rules" / "reaction_type_catalog.yaml").exists()
    assert (workspace / "prepare_report.yaml").exists()
    assert report["source_profile"] == "local_only"
    assert report["registry_mutated"] is False
    assert report["auto_promoted"] is False
    assert report["summary"]["properties_filled"] == 0
    assert _snapshot_yaml(registry) == original_registry


def test_enrich_with_internal_file_adds_property_and_reaction_without_mutating_registry(tmp_path):
    registry = _make_registry(tmp_path / "registry")
    internal_root = _make_internal_data(tmp_path / "internal_data")
    profile = _make_source_profile(tmp_path / "internal_profile.yaml", internal_root)
    case = _make_case(tmp_path / "case.yaml", ["CF4", "Xe"])
    workspace = tmp_path / "workspace"
    original_registry = _snapshot_yaml(registry)

    rc = main(
        [
            "enrich",
            str(case),
            "--registry",
            str(registry),
            "--workspace",
            str(workspace),
            "--source-profile",
            str(profile),
        ]
    )

    prepared_cf4 = _read_yaml(workspace / "prepared_registry" / "species" / "CF4.yaml")
    prepared_reaction = _read_yaml(workspace / "prepared_registry" / "reactions" / "electron" / "e__Xe.yaml")
    report = _read_yaml(workspace / "enrichment_report.yaml")

    assert rc == 0
    assert prepared_cf4["properties"]["polarizability_A3"]["value"] == 2.824
    assert prepared_cf4["properties"]["polarizability_A3"]["source_record"]["source_type"] == "internal_file_db"
    assert prepared_reaction["channels"][0]["id"] == "e_Xe_elastic"
    assert report["summary"]["properties_filled"] == 1
    assert report["summary"]["reaction_channels_imported"] == 1
    assert report["registry_mutated"] is False
    assert _snapshot_yaml(registry) == original_registry


def test_enriched_prepared_registry_can_be_used_with_generate(tmp_path):
    registry = _make_registry(tmp_path / "registry")
    internal_root = _make_internal_data(tmp_path / "internal_data")
    profile = _make_source_profile(tmp_path / "internal_profile.yaml", internal_root)
    case = _make_case(tmp_path / "case.yaml", ["CF4", "Xe"])
    workspace = tmp_path / "workspace"

    assert main(
        [
            "enrich",
            str(case),
            "--registry",
            str(registry),
            "--workspace",
            str(workspace),
            "--source-profile",
            str(profile),
        ]
    ) == 0

    output = tmp_path / "outputs"
    rc = main(
        [
            "generate",
            str(case),
            "--registry",
            str(workspace / "prepared_registry"),
            "--output",
            str(output),
        ]
    )

    network = _read_yaml(output / "network.reactions.yaml")
    assert rc == 0
    assert any(reaction["id"] == "e_Xe_elastic" for reaction in network["reactions"])


def _make_registry(root: Path) -> Path:
    _write_yaml(
        root / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "display_name": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "classes": ["neutral", "molecule"],
            "state": {"kind": "ground", "label": "X", "excitation_energy_eV": 0.0},
            "properties": {
                "polarizability_A3": {"value": None, "unit": "A3", "source": None},
            },
            "metadata": {"status": "curated", "notes": []},
        },
    )
    _write_yaml(
        root / "rules" / "reaction_type_catalog.yaml",
        {
            "schema_version": 1,
            "electron": {"elastic": {"expands_species": False}},
            "ion_neutral": {},
        },
    )
    _write_yaml(root / "rules" / "role_required_properties.yaml", {"schema_version": 1})
    return root


def _make_internal_data(root: Path) -> Path:
    _write_yaml(
        root / "species" / "species.yaml",
        [
            {
                "id": "Xe",
                "aliases": ["xenon"],
                "formula": "Xe",
                "composition": {"Xe": 1},
                "charge": 0,
                "classes": ["neutral", "atom"],
                "status": "curated",
                "source_record": {
                    "source_type": "internal_file_db",
                    "source_id": "internal_species:Xe",
                },
            }
        ],
    )
    _write_yaml(
        root / "properties" / "properties.yaml",
        [
            {
                "species": "CF4",
                "property": "polarizability_A3",
                "value": 2.824,
                "unit": "A3",
                "status": "curated",
                "source_record": {
                    "source_type": "internal_file_db",
                    "source_id": "internal_property:CF4:polarizability_A3",
                },
            }
        ],
    )
    _write_yaml(
        root / "reactions" / "electron.yaml",
        [
            {
                "pair": {"family": "electron", "projectile": "e", "target": "Xe"},
                "channels": [
                    {
                        "id": "e_Xe_elastic",
                        "type": "elastic",
                        "products": [{"species": "e", "n": 1}, {"species": "Xe", "n": 1}],
                        "status": "curated",
                        "threshold_eV": 0.0,
                        "data": {"cross_section": {"path": None}},
                    }
                ],
            }
        ],
    )
    return root


def _make_source_profile(path: Path, internal_root: Path) -> Path:
    _write_yaml(
        path,
        {
            "schema_version": 1,
            "name": "internal_enrich_test",
            "species_identity": ["internal_species_db", "local_registry"],
            "properties": ["internal_property_db", "local_registry"],
            "electron_cross_sections": ["local_assets"],
            "ion_neutral_reactions": ["internal_reaction_db", "local_registry"],
            "internal_file": {"root": str(internal_root)},
            "policy": {
                "prefer_status": ["curated", "literature_supported", "imported"],
                "require_review_for": [],
            },
        },
    )
    return path


def _make_case(path: Path, gases: list[str]) -> Path:
    _write_yaml(
        path,
        {
            "case": {"name": "enrich-test"},
            "gases": gases,
            "expansion": {"max_depth": 0},
            "outputs": {"csv_summary": False},
        },
    )
    return path


def _snapshot_yaml(root: Path) -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in sorted(root.rglob("*.yaml"))}


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
