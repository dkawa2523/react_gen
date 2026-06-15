from pathlib import Path

import yaml

from plasma_reactgen.data_sources.local_registry import (
    LocalAssetCrossSectionProvider,
    LocalRegistryPropertyProvider,
    LocalRegistryReactionProvider,
    LocalRegistrySpeciesProvider,
)
from plasma_reactgen.data_sources.registry import (
    get_providers,
    register_local_registry_providers,
    register_provider,
)
from plasma_reactgen.data_sources.source_profile import load_source_profile
from plasma_reactgen.domain.models import CollisionPair
from plasma_reactgen.infrastructure.file_registry import FileRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_load_builtin_local_only_without_profile_file(tmp_path):
    profile = load_source_profile("local_only", tmp_path / "registry")

    assert profile["name"] == "local_only"
    assert profile["species_identity"] == ["local_registry"]
    assert profile["properties"] == ["local_registry"]
    assert profile["electron_cross_sections"] == ["local_assets"]
    assert profile["ion_neutral_reactions"] == ["local_registry"]


def test_load_yaml_source_profile_by_name(tmp_path):
    profiles_dir = tmp_path / "registry" / "rules" / "source_profiles"
    profiles_dir.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "name": "custom_profile",
        "species_identity": ["custom_species"],
        "properties": ["custom_properties"],
        "electron_cross_sections": ["custom_cross_sections"],
        "ion_neutral_reactions": ["custom_reactions"],
        "policy": {"prefer_status": ["curated"], "require_review_for": []},
    }
    (profiles_dir / "custom_profile.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )

    profile = load_source_profile("custom_profile", tmp_path / "registry")

    assert profile == payload


def test_missing_source_profile_falls_back_to_local_only(tmp_path):
    profile = load_source_profile("does_not_exist", tmp_path / "registry")

    assert profile["name"] == "local_only"
    assert profile["species_identity"] == ["local_registry"]


def test_repository_yaml_profile_loads_by_name():
    profile = load_source_profile("experimental_first", ROOT / "registry")

    assert profile["name"] == "experimental_first"
    assert profile["species_identity"] == [
        "local_registry",
        "internal_species_db",
        "chemical_identity_snapshot",
        "pubchem_offline",
    ]
    assert profile["properties"] == [
        "local_registry",
        "internal_property_db",
        "nist_snapshot",
        "argonne_atct_snapshot",
        "chemicals_optional",
    ]


def test_provider_registry_preserves_profile_order_and_allows_override():
    first = object()
    second = object()
    replacement = object()

    register_provider("test_kind", "first", first)
    register_provider("test_kind", "second", second)

    providers = get_providers("test_kind", {"test_kind": ["second", "missing", "first"]})

    assert providers == [second, first]

    register_provider("test_kind", "first", replacement)

    providers = get_providers("test_kind", {"test_kind": ["first"]})

    assert providers == [replacement]


def test_local_species_provider_returns_sample_species():
    provider = LocalRegistrySpeciesProvider(FileRegistry(ROOT / "registry"))

    ar = provider.find_species("Ar")
    cf4 = provider.find_species("CF4")

    assert ar[0]["id"] == "Ar"
    assert ar[0]["composition"] == {"Ar": 1}
    assert ar[0]["charge"] == 0
    assert ar[0]["classes"] == ["atom", "neutral"]
    assert ar[0]["status"] == "curated"
    assert ar[0]["source_record"] == {
        "source_type": "local_registry",
        "source_id": "Ar",
    }

    assert cf4[0]["id"] == "CF4"
    assert cf4[0]["composition"] == {"C": 1, "F": 4}
    assert cf4[0]["properties"]["mass_amu"]["value"] == 88.0043


def test_local_property_provider_returns_requested_properties_only():
    provider = LocalRegistryPropertyProvider(FileRegistry(ROOT / "registry"))

    properties = provider.find_properties(
        "CF4",
        ["mass_amu", "missing_property", "dipole_moment_D"],
    )

    assert [item["property"] for item in properties] == [
        "mass_amu",
        "dipole_moment_D",
    ]
    assert properties[0]["species"] == "CF4"
    assert properties[0]["value"] == 88.0043
    assert properties[0]["unit"] == "amu"
    assert properties[0]["source_record"] == {
        "source_type": "local_registry",
        "source_id": "CF4.mass_amu",
    }


def test_local_reaction_provider_returns_electron_cf4_channels():
    registry = FileRegistry(ROOT / "registry")
    provider = LocalRegistryReactionProvider(registry)
    pair = CollisionPair("electron", "e", "CF4")

    channels = provider.find_channels(pair)

    assert channels
    assert channels[0]["pair"] == {
        "family": "electron",
        "projectile": "e",
        "target": "CF4",
    }
    assert {channel["type"] for channel in channels} >= {"elastic", "ionization"}
    assert channels[0]["source_record"] == {
        "source_type": "local_registry",
        "source_id": "e_CF4_elastic",
    }


def test_local_asset_provider_marks_null_cross_section_paths_missing():
    registry = FileRegistry(ROOT / "registry")
    provider = LocalAssetCrossSectionProvider(registry)
    pair = CollisionPair("electron", "e", "CF4")

    cross_sections = provider.find_cross_sections(pair)

    assert cross_sections
    assert {candidate["status"] for candidate in cross_sections} == {"missing"}
    assert all(candidate["path"] is None for candidate in cross_sections)
    assert cross_sections[0]["source_record"] == {
        "source_type": "local_assets",
        "source_id": "e_CF4_elastic",
    }


def test_register_local_registry_providers_returns_functional_providers():
    registry = FileRegistry(ROOT / "registry")
    register_local_registry_providers(registry)

    species_providers = get_providers(
        "species_identity",
        {"species_identity": ["local_registry"]},
    )
    asset_providers = get_providers(
        "electron_cross_sections",
        {"electron_cross_sections": ["local_assets"]},
    )

    assert species_providers[0].find_species("Ar")[0]["id"] == "Ar"
    assert asset_providers[0].find_cross_sections(
        CollisionPair("electron", "e", "CF4")
    )


def test_local_providers_do_not_mutate_registry_files():
    paths = [
        ROOT / "registry" / "species" / "Ar.yaml",
        ROOT / "registry" / "species" / "CF4.yaml",
        ROOT / "registry" / "reactions" / "electron" / "e__CF4.yaml",
    ]
    before = {path: path.read_text(encoding="utf-8") for path in paths}
    registry = FileRegistry(ROOT / "registry")

    LocalRegistrySpeciesProvider(registry).find_species("Ar")
    LocalRegistryPropertyProvider(registry).find_properties("CF4", None)
    LocalRegistryReactionProvider(registry).find_channels(CollisionPair("electron", "e", "CF4"))
    LocalAssetCrossSectionProvider(registry).find_cross_sections(CollisionPair("electron", "e", "CF4"))

    after = {path: path.read_text(encoding="utf-8") for path in paths}
    assert after == before
