from pathlib import Path

import yaml

from plasma_reactgen.infrastructure.file_registry import FileRegistry


def test_species_property_source_record_survives_registry_loading(tmp_path):
    registry_root = tmp_path / "registry"
    _write_yaml(
        registry_root / "species" / "CF4.yaml",
        {
            "id": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "classes": ["neutral", "molecule"],
            "properties": {
                "mass_amu": {
                    "value": 88.0,
                    "unit": "amu",
                    "source": "internal_file_db",
                    "source_record": {
                        "source_type": "internal_file_db",
                        "source_id": "property:CF4:mass_amu",
                    },
                }
            },
        },
    )

    species = FileRegistry(registry_root).get_species("CF4")

    assert species is not None
    assert species.properties["mass_amu"].source_record == {
        "source_type": "internal_file_db",
        "source_id": "property:CF4:mass_amu",
    }


def test_asset_exists_requires_a_file_inside_registry(tmp_path):
    registry_root = tmp_path / "registry"
    asset = registry_root / "assets" / "cross_sections" / "elastic.csv"
    asset.parent.mkdir(parents=True)
    asset.write_text("energy_eV,cross_section_m2\n", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("not a registry asset\n", encoding="utf-8")
    registry = FileRegistry(registry_root)

    assert registry.asset_exists("assets/cross_sections/elastic.csv") is True
    assert registry.asset_exists("assets/cross_sections") is False
    assert registry.asset_exists("../outside.csv") is False
    assert registry.asset_exists(outside) is False


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
