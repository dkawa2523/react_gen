from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


_POLICY = {
    "prefer_status": [
        "curated",
        "literature_supported",
        "imported",
        "estimated",
        "inferred",
    ],
    "require_review_for": [
        "conflicting_values",
        "estimated_collision_radius",
        "llm_extracted",
    ],
}

_PUBCHEM_PLACEHOLDER = {
    "enabled": False,
    "mode": "online",
    "cache_dir": "external_data/pubchem/cache",
}

_COMMON_DISABLED_SOURCES = [
    "pubchem_online",
    "vamdc",
    "openadas",
]

_COMMON_EXTERNAL_ONLY_SOURCES = [
    "pubchem_fetch",
    "lxcat_raw_import",
    "openadas_raw_import",
    "vamdc_query",
]

_LOCAL_METADATA = {
    "active_sources": [
        "local_registry",
        "local_assets",
    ],
    "optional_sources": [
        "internal_file",
        "nist_snapshot",
        "chemicals_optional",
    ],
    "disabled_sources": _COMMON_DISABLED_SOURCES,
    "external_only_sources": _COMMON_EXTERNAL_ONLY_SOURCES,
}

_ENRICHMENT_METADATA = {
    "active_sources": [
        "local_registry",
        "local_assets",
    ],
    "optional_sources": [
        "internal_file",
        "chemical_identity_snapshot",
        "nist_snapshot",
        "argonne_atct_snapshot",
        "chemicals_optional",
        "lxcat_offline",
        "ion_reaction_table",
    ],
    "disabled_sources": _COMMON_DISABLED_SOURCES,
    "external_only_sources": _COMMON_EXTERNAL_ONLY_SOURCES,
}

_BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "local_only": {
        "schema_version": 1,
        "name": "local_only",
        **_LOCAL_METADATA,
        "species_identity": ["local_registry"],
        "properties": ["local_registry"],
        "electron_cross_sections": ["local_assets"],
        "ion_neutral_reactions": ["local_registry"],
        "pubchem": _PUBCHEM_PLACEHOLDER,
        "policy": _POLICY,
    },
    "experimental_first": {
        "schema_version": 1,
        "name": "experimental_first",
        **_ENRICHMENT_METADATA,
        "species_identity": [
            "local_registry",
            "internal_species_db",
            "chemical_identity_snapshot",
            "pubchem_offline",
        ],
        "properties": [
            "local_registry",
            "internal_property_db",
            "nist_snapshot",
            "argonne_atct_snapshot",
            "chemicals_optional",
        ],
        "electron_cross_sections": [
            "local_assets",
            "internal_cross_section_db",
            "lxcat_offline",
        ],
        "ion_neutral_reactions": [
            "local_registry",
            "internal_reaction_db",
            "literature_candidates",
        ],
        "pubchem": _PUBCHEM_PLACEHOLDER,
        "policy": _POLICY,
    },
    "internal_first": {
        "schema_version": 1,
        "name": "internal_first",
        **_ENRICHMENT_METADATA,
        "species_identity": [
            "internal_species_db",
            "local_registry",
            "chemical_identity_snapshot",
            "pubchem_offline",
        ],
        "properties": [
            "internal_property_db",
            "local_registry",
            "nist_snapshot",
            "argonne_atct_snapshot",
            "chemicals_optional",
        ],
        "electron_cross_sections": [
            "internal_cross_section_db",
            "local_assets",
            "lxcat_offline",
        ],
        "ion_neutral_reactions": [
            "internal_reaction_db",
            "local_registry",
            "literature_candidates",
        ],
        "pubchem": _PUBCHEM_PLACEHOLDER,
        "policy": _POLICY,
    },
}


def load_source_profile(path_or_name: str | None, registry_root: Path) -> dict[str, Any]:
    """Load a prepare-time source profile by path or registry profile name."""

    registry_root = Path(registry_root)
    if path_or_name is None:
        return _builtin_profile("local_only")

    candidate_path = Path(path_or_name)
    if candidate_path.exists():
        return _read_profile(candidate_path)

    profile_name = str(path_or_name)
    profile_path = registry_root / "rules" / "source_profiles" / f"{profile_name}.yaml"
    if profile_path.exists():
        return _read_profile(profile_path)

    if profile_name in _BUILTIN_PROFILES:
        return _builtin_profile(profile_name)

    return _builtin_profile("local_only")


def _builtin_profile(name: str) -> dict[str, Any]:
    return deepcopy(_BUILTIN_PROFILES[name])


def _read_profile(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"source profile is not valid YAML: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"source profile must be a YAML mapping: {path}")
    return data
