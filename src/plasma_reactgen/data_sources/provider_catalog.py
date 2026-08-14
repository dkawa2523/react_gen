from __future__ import annotations

_PROVIDER_NAMES = {
    "species_identity": (
        "local_registry",
        "internal_species_db",
        "internal_file",
        "chemical_identity_snapshot",
        "chemicals_optional",
        "chemicals_local",
    ),
    "properties": (
        "local_registry",
        "internal_property_db",
        "internal_file",
        "nist_snapshot",
        "argonne_atct_snapshot",
        "chemicals_optional",
        "chemicals_local",
    ),
    "ion_neutral_reactions": (
        "local_registry",
        "internal_reaction_db",
        "internal_file",
        "ion_reaction_table",
        "literature_candidates",
    ),
    "electron_reactions": (
        "local_registry",
        "internal_reaction_db",
        "internal_file",
    ),
}


def available_provider_names() -> dict[str, list[str]]:
    """Return a mutable copy of the supported local provider catalog."""

    return {section: list(names) for section, names in _PROVIDER_NAMES.items()}
