from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plasma_reactgen.data_sources.provider_builders import (
    ProviderBuilder,
    ProviderBuildResult,
    SourceProviderConfigurationError,
)
from plasma_reactgen.data_sources.provider_catalog import available_provider_names

ProviderFactory = Callable[[], list[Any]]
ProviderEntry = tuple[str, ProviderFactory]

__all__ = [
    "ProviderBuildResult",
    "SourceProviderConfigurationError",
    "available_provider_names",
    "build_property_providers",
    "build_reaction_providers",
    "build_species_providers",
]


def build_species_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = ProviderBuilder(profile)
    providers = _build_in_profile_order(
        builder,
        ("species_identity",),
        {
            "internal_file": ("internal_file", builder.internal_species),
            "internal_species_db": ("internal_file", builder.internal_species),
            "chemicals_optional": ("chemicals", builder.chemicals_species),
            "chemicals_local": ("chemicals", builder.chemicals_species),
        },
    )
    return builder.result(providers)


def build_property_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = ProviderBuilder(profile)
    providers = _build_in_profile_order(
        builder,
        ("properties",),
        {
            "internal_file": ("internal_file", builder.internal_properties),
            "internal_property_db": ("internal_file", builder.internal_properties),
            "nist_snapshot": ("nist_snapshot", builder.nist_properties),
            "argonne_atct_snapshot": (
                "argonne_atct_snapshot",
                builder.argonne_atct_properties,
            ),
            "chemicals_optional": ("chemicals", builder.chemicals_properties),
            "chemicals_local": ("chemicals", builder.chemicals_properties),
        },
    )
    return builder.result(providers)


def build_reaction_providers(profile: dict[str, Any]) -> ProviderBuildResult:
    builder = ProviderBuilder(profile)
    providers = _build_in_profile_order(
        builder,
        ("electron_reactions", "ion_neutral_reactions"),
        {
            "internal_file": ("internal_file", builder.internal_reactions),
            "internal_reaction_db": ("internal_file", builder.internal_reactions),
            "ion_reaction_table": ("ion_reaction_table", builder.ion_reaction_tables),
        },
    )
    return builder.result(providers)


def _build_in_profile_order(
    builder: ProviderBuilder,
    sections: tuple[str, ...],
    factories: dict[str, ProviderEntry],
) -> list[Any]:
    providers: list[Any] = []
    built_sources: set[str] = set()
    for name in builder.profile.names(*sections):
        entry = factories.get(name)
        if entry is None:
            continue
        source_name, factory = entry
        if source_name in built_sources:
            continue
        providers.extend(factory())
        built_sources.add(source_name)
    return providers
