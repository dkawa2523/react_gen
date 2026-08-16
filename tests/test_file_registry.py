from pathlib import Path

import pytest
import yaml

from plasma_reactgen.domain.models import CollisionPair
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


def test_legacy_cross_section_is_normalized_as_dataset(tmp_path):
    registry = _registry_with_channel(
        tmp_path,
        {
            "id": "e_A_elastic",
            "type": "elastic",
            "products": [{"species": "e"}, {"species": "A"}],
            "data": {
                "cross_section": {
                    "status": "local_file_registered",
                    "path": "assets/cross_sections/e_A.csv",
                    "source": "lxcat_offline",
                }
            },
        },
    )

    channel = registry.get_channels(CollisionPair("electron", "e", "A"))[0]

    assert len(channel.datasets) == 1
    assert channel.datasets[0].kind == "cross_section"
    assert channel.datasets[0].asset.path == "assets/cross_sections/e_A.csv"
    assert channel.datasets[0].source.source_type == "lxcat_offline"
    assert channel.data["cross_section"]["path"] == "assets/cross_sections/e_A.csv"


def test_multiple_datasets_and_provenance_survive_registry_loading(tmp_path):
    registry = _registry_with_channel(
        tmp_path,
        {
            "id": "ion_Ap_A_ct",
            "type": "charge_transfer",
            "products": [{"species": "A"}, {"species": "A+"}],
            "evidence": {"source_type": "literature", "source_id": "paper:1"},
            "provenance": {"source_type": "registry", "source_id": "channel:1"},
            "source_record": {"source_type": "snapshot", "source_id": "row:1"},
            "confidence": {"score": 0.9},
            "data": {
                "datasets": [
                    {
                        "id": "ds_rate_1",
                        "kind": "rate_coefficient",
                        "representation": "arrhenius",
                        "unit": "m3/s",
                        "parameters": {"A": 1.0e-15, "n": 0.5},
                    },
                    {
                        "id": "ds_rate_2",
                        "kind": "rate_coefficient",
                        "representation": "constant",
                        "unit": "m3/s",
                        "parameters": {"k": 2.0e-15},
                        "preferred": True,
                    },
                ]
            },
        },
        family="ion_neutral",
        projectile="A+",
        target="A",
    )

    channel = registry.get_channels(CollisionPair("ion_neutral", "A+", "A"))[0]

    assert [dataset.id for dataset in channel.datasets] == ["ds_rate_1", "ds_rate_2"]
    assert channel.datasets[0].parameters == {"A": 1.0e-15, "n": 0.5}
    assert channel.evidence["source_id"] == "paper:1"
    assert channel.provenance["source_id"] == "channel:1"
    assert channel.source_record["source_id"] == "row:1"
    assert channel.confidence == {"score": 0.9}


def test_duplicate_pair_is_rejected_during_registry_loading(tmp_path):
    root = tmp_path / "registry"
    pair = {
        "pair": {"family": "electron", "projectile": "e", "target": "A"},
        "channels": [],
    }
    _write_yaml(root / "reactions" / "electron" / "first.yaml", pair)
    _write_yaml(root / "reactions" / "electron" / "second.yaml", pair)

    with pytest.raises(ValueError, match="duplicate reaction pair"):
        FileRegistry(root)


def test_duplicate_species_id_is_rejected_during_registry_loading(tmp_path):
    root = tmp_path / "registry"
    species = {"id": "A", "composition": {"A": 1}, "charge": 0}
    _write_yaml(root / "species" / "first.yaml", species)
    _write_yaml(root / "species" / "second.yaml", species)

    with pytest.raises(ValueError, match="duplicate species id"):
        FileRegistry(root)


def test_duplicate_channel_id_is_rejected_during_registry_loading(tmp_path):
    root = tmp_path / "registry"
    for target in ("A", "B"):
        _write_yaml(
            root / "reactions" / "electron" / f"{target}.yaml",
            {
                "pair": {"family": "electron", "projectile": "e", "target": target},
                "channels": [{"id": "duplicate", "type": "elastic", "products": []}],
            },
        )

    with pytest.raises(ValueError, match="duplicate reaction channel id"):
        FileRegistry(root)


def test_incomplete_reaction_pair_is_not_indexed(tmp_path):
    root = tmp_path / "registry"
    _write_yaml(
        root / "reactions" / "electron" / "incomplete.yaml",
        {
            "pair": {"family": "electron", "projectile": "e"},
            "channels": [{"id": "ignored", "type": "elastic", "products": []}],
        },
    )

    registry = FileRegistry(root)

    assert registry.iter_reaction_files()
    assert registry.find_pairs_involving({"e", "A"}, {"A"}) == []


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _registry_with_channel(
    tmp_path: Path,
    channel: dict,
    *,
    family: str = "electron",
    projectile: str = "e",
    target: str = "A",
) -> FileRegistry:
    root = tmp_path / "registry"
    _write_yaml(
        root / "reactions" / family / "pair.yaml",
        {
            "pair": {
                "family": family,
                "projectile": projectile,
                "target": target,
            },
            "channels": [channel],
        },
    )
    return FileRegistry(root)
