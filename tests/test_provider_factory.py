from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from plasma_reactgen.data_sources.provider_factory import (
    SourceProviderConfigurationError,
    available_provider_names,
    build_property_providers,
    build_reaction_providers,
    build_species_providers,
)
from plasma_reactgen.preparation import prepare_case


def test_provider_factory_treats_local_registry_as_baseline_not_enrichment(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path / "registry")
    result = build_species_providers(
        {
            "name": "local_provider_test",
            "species_identity": ["local_registry"],
            "local_registry": {"root": str(registry)},
        }
    )

    assert not result.warnings
    assert result.providers == []
    assert "local_registry" in available_provider_names()["species_identity"]


def test_provider_factory_missing_config_warns_without_crashing() -> None:
    result = build_property_providers(
        {
            "name": "missing_nist_root",
            "properties": ["nist_snapshot"],
        }
    )

    assert result.providers == []
    assert result.warnings == [
        {
            "source": "nist_snapshot",
            "section": "properties",
            "reason": "missing_config",
            "required": "nist_snapshot.root",
        }
    ]
    assert result.unavailable_sources == result.warnings


def test_provider_factory_strict_sources_raises_on_missing_config() -> None:
    with pytest.raises(SourceProviderConfigurationError):
        build_property_providers(
            {
                "name": "strict_missing_nist_root",
                "strict_sources": True,
                "properties": ["nist_snapshot"],
            }
        )


def test_provider_factory_builds_internal_and_nist_providers(tmp_path: Path) -> None:
    internal_root = _make_internal_data(tmp_path / "internal_data")
    nist_root = _make_nist_snapshot(tmp_path / "nist")

    properties = build_property_providers(
        {
            "name": "provider_factory_sources",
            "properties": ["internal_property_db", "nist_snapshot"],
            "internal_file": {"root": str(internal_root)},
            "nist_snapshot": {"root": str(nist_root)},
        }
    )
    reactions = build_reaction_providers(
        {
            "name": "provider_factory_sources",
            "ion_neutral_reactions": ["internal_reaction_db"],
            "internal_file": {"root": str(internal_root)},
        }
    )

    assert [
        candidate["value"]
        for candidate in properties.providers[0].find_properties("CF4", ["polarizability_A3"])
    ] == [2.824]
    assert [
        candidate["value"]
        for candidate in properties.providers[1].find_properties("CF4", ["ionization_energy_eV"])
    ] == [14.7]
    assert (
        reactions.providers[0].find_channels(_pair("electron", "e", "Xe"))[0]["id"]
        == "e_Xe_elastic"
    )


def test_provider_factory_deduplicates_aliases_and_honors_disabled_sources(
    tmp_path: Path,
) -> None:
    internal_root = _make_internal_data(tmp_path / "internal_data")
    profile = {
        "properties": ["internal_file", "internal_property_db"],
        "internal_file": {"root": str(internal_root)},
    }

    assert len(build_property_providers(profile).providers) == 1
    profile["disabled_sources"] = ["internal_file"]
    assert build_property_providers(profile).providers == []


def test_prepare_case_still_uses_internal_file_and_nist_sources(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path / "registry")
    internal_root = _make_internal_data(tmp_path / "internal_data")
    nist_root = _make_nist_snapshot(tmp_path / "nist")
    case = _make_case(tmp_path / "case.yaml")
    prepared = tmp_path / "prepared_registry"

    report = prepare_case(
        input_path=case,
        registry_root=registry,
        source_profile={
            "name": "factory_prepare_equivalence",
            "species_identity": ["internal_species_db"],
            "properties": ["internal_property_db", "nist_snapshot"],
            "ion_neutral_reactions": ["internal_reaction_db"],
            "internal_file": {"root": str(internal_root)},
            "nist_snapshot": {"root": str(nist_root)},
        },
        output_dir=prepared,
    )

    species = _read_yaml(prepared / "species" / "CF4.yaml")
    reactions = _read_yaml(prepared / "reactions" / "electron" / "e__Xe.yaml")
    assert species["properties"]["polarizability_A3"]["value"] == 2.824
    assert species["properties"]["ionization_energy_eV"]["value"] == 14.7
    assert reactions["channels"][0]["id"] == "e_Xe_elastic"
    assert report["schema_version"] == 2


def _pair(family: str, projectile: str, target: str):
    from plasma_reactgen.domain.models import CollisionPair

    return CollisionPair(family, projectile, target)


def _make_registry(root: Path) -> Path:
    _write_yaml(
        root / "species" / "Ar.yaml",
        {
            "schema_version": 1,
            "id": "Ar",
            "composition": {"Ar": 1},
            "charge": 0,
            "classes": ["neutral", "atom"],
            "state": {},
            "properties": {},
            "metadata": {"status": "curated"},
        },
    )
    _write_yaml(
        root / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "classes": ["neutral", "molecule"],
            "state": {},
            "properties": {
                "polarizability_A3": {"value": None, "unit": "A3", "source": None},
                "ionization_energy_eV": {"value": None, "unit": "eV", "source": None},
            },
            "metadata": {"status": "curated"},
        },
    )
    _write_yaml(
        root / "rules" / "reaction_type_catalog.yaml",
        {"schema_version": 1, "electron": {"elastic": {}}},
    )
    return root


def _make_internal_data(root: Path) -> Path:
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
                    }
                ],
            }
        ],
    )
    _write_yaml(
        root / "species" / "species.yaml",
        [
            {
                "id": "Xe",
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
    return root


def _make_nist_snapshot(root: Path) -> Path:
    _write_yaml(
        root / "species_properties.yaml",
        [
            {
                "species": "CF4",
                "property": "ionization_energy_eV",
                "value": 14.7,
                "unit": "eV",
                "status": "literature_supported",
                "source_record": {
                    "source_type": "public_database_snapshot",
                    "database": "NIST",
                    "source_id": "nist:CF4:IE",
                },
            }
        ],
    )
    return root


def _make_case(path: Path) -> Path:
    _write_yaml(
        path,
        {
            "case": {"name": "provider-factory-prepare"},
            "gases": ["CF4", "Xe"],
            "expansion": {"max_depth": 0},
        },
    )
    return path


def _write_yaml(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
