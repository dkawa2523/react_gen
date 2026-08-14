from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from plasma_reactgen.data_sources.provider_factory import (
    build_property_providers,
    build_reaction_providers,
    build_species_providers,
)
from plasma_reactgen.data_sources.source_catalog import (
    license_review_items,
    load_source_catalog,
)
from plasma_reactgen.data_sources.source_configuration import (
    configured_optional_sources,
    profile_list,
)
from plasma_reactgen.data_sources.source_listing_format import (
    format_source_list_report as format_source_list_report,
)
from plasma_reactgen.data_sources.source_profile import load_source_profile


def build_source_list_report(
    source_profile: str | None,
    registry_root: str | Path,
    *,
    source_catalog: str | Path | None = None,
) -> dict[str, Any]:
    registry_root = Path(registry_root)
    profile = load_source_profile(source_profile, registry_root)
    factory_profile = _profile_for_factory(profile, registry_root)

    species_result = build_species_providers(factory_profile)
    property_result = build_property_providers(factory_profile)
    reaction_result = build_reaction_providers(factory_profile)
    warnings = [
        *species_result.warnings,
        *property_result.warnings,
        *reaction_result.warnings,
    ]

    configured_optional = configured_optional_sources(profile)
    catalog = load_source_catalog(source_catalog, registry_root)

    return {
        "schema_version": 1,
        "source_profile": profile.get("name", source_profile or "local_only"),
        "active_sources": profile_list(profile, "active_sources"),
        "optional_sources": profile_list(profile, "optional_sources"),
        "optional_configured_sources": configured_optional,
        "disabled_sources": profile_list(profile, "disabled_sources"),
        "external_only_sources": profile_list(profile, "external_only_sources"),
        "missing_configuration": warnings,
        "license_review_required": license_review_items(profile, configured_optional, catalog),
        "provider_counts": {
            "species": len(species_result.providers),
            "properties": len(property_result.providers),
            "reactions": len(reaction_result.providers),
        },
    }


def _profile_for_factory(profile: dict[str, Any], registry_root: Path) -> dict[str, Any]:
    prepared = deepcopy(profile)
    prepared.setdefault("local_registry", {})["root"] = str(registry_root)
    return prepared
