from __future__ import annotations

from typing import Any

SOURCE_SECTIONS = (
    "species_identity",
    "properties",
    "electron_cross_sections",
    "ion_neutral_reactions",
    "electron_reactions",
)

CONFIGURATION_FIELDS = {
    "internal_file": "root",
    "nist_snapshot": "root",
    "argonne_atct_snapshot": "files",
    "chemical_identity_snapshot": "snapshot",
    "ion_reaction_table": "files",
}


def profile_list(profile: dict[str, Any], key: str) -> list[str]:
    value = profile.get(key, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def configured_optional_sources(profile: dict[str, Any]) -> list[str]:
    return [
        source
        for source in profile_list(profile, "optional_sources")
        if source_is_configured_or_selected(profile, source)
    ]


def source_is_configured_or_selected(profile: dict[str, Any], source: str) -> bool:
    field = CONFIGURATION_FIELDS.get(source)
    if field is not None:
        configuration = profile.get(source)
        return isinstance(configuration, dict) and bool(configuration.get(field))
    return any(source in profile_list(profile, section) for section in SOURCE_SECTIONS)
