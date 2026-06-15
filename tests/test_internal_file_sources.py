from pathlib import Path

import yaml

from plasma_reactgen.data_sources.internal_file import (
    InternalFileCrossSectionProvider,
    InternalFilePropertyProvider,
    InternalFileReactionProvider,
    InternalFileSpeciesProvider,
)
from plasma_reactgen.data_sources.registry import (
    get_providers,
    register_internal_file_providers,
)
from plasma_reactgen.domain.models import CollisionPair
from plasma_reactgen.preparation import prepare_case


def test_internal_species_provider_queries_by_id_or_alias(tmp_path):
    internal_root = _make_internal_data(tmp_path / "internal_data")
    provider = InternalFileSpeciesProvider(internal_root)

    by_id = provider.find_species("Xe")
    by_alias = provider.find_species("xenon")

    assert by_id[0]["id"] == "Xe"
    assert by_alias[0]["id"] == "Xe"
    assert by_id[0]["source_record"] == {
        "source_type": "internal_file_db",
        "source_id": "internal_species:Xe",
    }


def test_internal_property_provider_returns_matching_properties(tmp_path):
    internal_root = _make_internal_data(tmp_path / "internal_data")
    provider = InternalFilePropertyProvider(internal_root)

    properties = provider.find_properties("CF4", ["polarizability_A3", "missing"])

    assert len(properties) == 1
    assert properties[0]["species"] == "CF4"
    assert properties[0]["property"] == "polarizability_A3"
    assert properties[0]["value"] == 2.824
    assert properties[0]["source_record"]["source_id"] == "internal_property:CF4:polarizability_A3"


def test_internal_reaction_provider_returns_registry_shaped_channels(tmp_path):
    internal_root = _make_internal_data(tmp_path / "internal_data")
    provider = InternalFileReactionProvider(internal_root)

    channels = provider.find_channels(CollisionPair("electron", "e", "Xe"))

    assert channels == [
        {
            "id": "e_Xe_elastic",
            "type": "elastic",
            "products": [{"species": "e", "n": 1}, {"species": "Xe", "n": 1}],
            "status": "curated",
            "threshold_eV": 0.0,
            "data": {
                "cross_section": {
                    "path": "cross_sections/files/e_xe.csv",
                    "format": "csv_energy_eV_sigma_m2",
                }
            },
            "pair": {"family": "electron", "projectile": "e", "target": "Xe"},
            "source_record": {
                "source_type": "internal_file_db",
                "source_id": "internal_reaction:e_Xe_elastic",
            },
        }
    ]


def test_internal_cross_section_provider_registers_asset_metadata(tmp_path):
    internal_root = _make_internal_data(tmp_path / "internal_data")
    provider = InternalFileCrossSectionProvider(internal_root)

    by_channel = provider.find_cross_sections("e_Xe_elastic")
    by_pair = provider.find_cross_sections(CollisionPair("electron", "e", "Xe"))

    assert by_channel == by_pair
    assert by_channel[0]["channel_id"] == "e_Xe_elastic"
    assert by_channel[0]["path"] == "cross_sections/files/e_xe.csv"
    assert by_channel[0]["status"] == "internal_file_registered"
    assert by_channel[0]["source_record"] == {
        "source_type": "internal_file_db",
        "source_id": "internal_cross_section:e_Xe_elastic",
    }


def test_register_internal_file_providers_makes_profile_entries_functional(tmp_path):
    internal_root = _make_internal_data(tmp_path / "internal_data")
    register_internal_file_providers(internal_root)

    species_provider = get_providers(
        "species_identity",
        {"species_identity": ["internal_species_db"]},
    )[0]
    reaction_provider = get_providers(
        "electron_reactions",
        {"electron_reactions": ["internal_reaction_db"]},
    )[0]

    assert species_provider.find_species("Xe")[0]["id"] == "Xe"
    assert reaction_provider.find_channels(CollisionPair("electron", "e", "Xe"))


def test_prepare_case_writes_internal_data_to_prepared_registry_without_mutating_registry(tmp_path):
    registry_root = _make_registry_with_missing_cf4_property(tmp_path / "registry")
    internal_root = _make_internal_data(tmp_path / "internal_data")
    input_path = tmp_path / "case.yaml"
    output_dir = tmp_path / "prepared_registry"
    input_path.write_text(
        yaml.safe_dump(
            {
                "case": {"name": "internal-file-test"},
                "gases": ["CF4", "Xe"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    original_registry = {
        path: path.read_text(encoding="utf-8")
        for path in registry_root.rglob("*.yaml")
    }

    report = prepare_case(
        input_path=input_path,
        registry_root=registry_root,
        source_profile={
            "name": "internal_file_test",
            "internal_file": {"root": str(internal_root)},
        },
        output_dir=output_dir,
    )

    prepared_xe = yaml.safe_load((output_dir / "species" / "Xe.yaml").read_text(encoding="utf-8"))
    prepared_cf4 = yaml.safe_load((output_dir / "species" / "CF4.yaml").read_text(encoding="utf-8"))
    prepared_reactions = yaml.safe_load(
        (output_dir / "reactions" / "electron" / "e__Xe.yaml").read_text(encoding="utf-8")
    )
    report_payload = yaml.safe_load((output_dir / "prepare_report.yaml").read_text(encoding="utf-8"))

    assert prepared_xe["metadata"]["source_record"] == {
        "source_type": "internal_file_db",
        "source_id": "internal_species:Xe",
    }
    assert prepared_cf4["properties"]["polarizability_A3"]["value"] == 2.824
    assert prepared_cf4["properties"]["polarizability_A3"]["source_record"] == {
        "source_type": "internal_file_db",
        "source_id": "internal_property:CF4:polarizability_A3",
    }
    assert prepared_reactions["channels"][0]["id"] == "e_Xe_elastic"
    assert prepared_reactions["channels"][0]["source_record"]["source_type"] == "internal_file_db"
    assert report["registry_mutated"] is False
    assert report_payload["summary"]["n_species_written"] == 1
    assert report_payload["summary"]["n_properties_written"] == 1
    assert report_payload["summary"]["n_reaction_files_written"] == 1
    assert {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")} == original_registry


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
                "evidence_type": "experimental",
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
                        "data": {
                            "cross_section": {
                                "path": "cross_sections/files/e_xe.csv",
                                "format": "csv_energy_eV_sigma_m2",
                            }
                        },
                    }
                ],
            }
        ],
    )
    _write_yaml(
        root / "cross_sections" / "index.yaml",
        [
            {
                "channel_id": "e_Xe_elastic",
                "pair": {"family": "electron", "projectile": "e", "target": "Xe"},
                "path": "cross_sections/files/e_xe.csv",
                "format": "csv_energy_eV_sigma_m2",
            }
        ],
    )
    data_file = root / "cross_sections" / "files" / "e_xe.csv"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text("energy_eV,sigma_m2\n0,0\n", encoding="utf-8")
    return root


def _make_registry_with_missing_cf4_property(root: Path) -> Path:
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
                "polarizability_A3": {"value": None, "unit": "A3", "source": None}
            },
            "metadata": {"status": "curated", "notes": []},
        },
    )
    return root


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
