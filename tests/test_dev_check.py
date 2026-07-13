from pathlib import Path

import yaml

from plasma_reactgen.infrastructure.indexer import check_registry_details
from plasma_reactgen.interface.cli import main


def test_dev_check_fails_for_missing_registry(tmp_path: Path) -> None:
    missing = tmp_path / "missing_registry"

    assert main(["dev-check", "--registry", str(missing), "--strict"]) == 1
    details = check_registry_details(missing, strict=True)
    assert details["errors"]


def test_dev_check_detects_duplicate_species_and_pair_ids(tmp_path: Path) -> None:
    registry = _minimal_registry(tmp_path)
    _write_yaml(
        registry / "species" / "Ar_duplicate.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "charge": 0, "classes": ["neutral"]},
    )
    pair = {
        "pair": {"family": "electron", "projectile": "e", "target": "Ar"},
        "channels": [],
    }
    _write_yaml(registry / "reactions" / "electron" / "duplicate.yaml", pair)

    details = check_registry_details(registry)

    assert any("duplicate species id 'Ar'" in error for error in details["errors"])
    assert any("duplicate reaction pair 'electron|e|Ar'" in error for error in details["errors"])
    assert main(["dev-check", "--registry", str(registry)]) == 1


def _minimal_registry(root: Path) -> Path:
    _write_yaml(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "charge": 0, "classes": ["neutral"]},
    )
    _write_yaml(
        root / "reactions" / "electron" / "e__Ar.yaml",
        {
            "pair": {"family": "electron", "projectile": "e", "target": "Ar"},
            "channels": [],
        },
    )
    _write_yaml(root / "rules" / "reaction_type_catalog.yaml", {"schema_version": 1})
    _write_yaml(root / "rules" / "role_required_properties.yaml", {"schema_version": 1, "roles": {}})
    return root


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
