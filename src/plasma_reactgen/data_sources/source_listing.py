from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.data_sources.provider_factory import (
    build_property_providers,
    build_reaction_providers,
    build_species_providers,
)
from plasma_reactgen.data_sources.source_profile import load_source_profile


SOURCE_SECTIONS = (
    "species_identity",
    "properties",
    "electron_cross_sections",
    "ion_neutral_reactions",
    "electron_reactions",
)

SOURCE_CATALOG_ALIASES = {
    "local_assets": "user_provided_cross_section_csv",
    "internal_species_db": "internal_file",
    "internal_property_db": "internal_file",
    "internal_reaction_db": "internal_file",
    "internal_cross_section_db": "internal_file",
    "pubchem_online": "pubchem",
    "pubchem_offline": "pubchem",
    "pubchem_fetch": "pubchem",
    "openadas_raw_import": "openadas",
    "vamdc_query": "vamdc",
    "lxcat_raw_import": "lxcat_offline",
    "chemicals_local": "chemicals_optional",
}


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

    configured_optional = [
        source for source in _list(profile, "optional_sources") if _source_is_configured_or_selected(profile, source)
    ]
    catalog = _load_source_catalog(source_catalog, registry_root)

    return {
        "schema_version": 1,
        "source_profile": profile.get("name", source_profile or "local_only"),
        "active_sources": _list(profile, "active_sources"),
        "optional_sources": _list(profile, "optional_sources"),
        "optional_configured_sources": configured_optional,
        "disabled_sources": _list(profile, "disabled_sources"),
        "external_only_sources": _list(profile, "external_only_sources"),
        "missing_configuration": warnings,
        "license_review_required": _license_review_required(profile, configured_optional, catalog),
        "provider_counts": {
            "species": len(species_result.providers),
            "properties": len(property_result.providers),
            "reactions": len(reaction_result.providers),
        },
    }


def format_source_list_report(report: dict[str, Any]) -> str:
    lines = [
        f"Source profile: {report['source_profile']}",
        "Active sources: " + _format_list(report["active_sources"]),
        "Optional sources: " + _format_list(report["optional_sources"]),
        "Optional configured sources: " + _format_list(report["optional_configured_sources"]),
        "Disabled sources: " + _format_list(report["disabled_sources"]),
        "External-only sources: " + _format_list(report["external_only_sources"]),
    ]
    if report["missing_configuration"]:
        lines.append("Missing configuration:")
        for item in report["missing_configuration"]:
            lines.append(f"  - {item['source']} ({item['section']}): requires {item['required']}")
    else:
        lines.append("Missing configuration: none")

    if report["license_review_required"]:
        lines.append("License review required:")
        for item in report["license_review_required"]:
            note = item.get("notes") or ""
            lines.append(f"  - {item['source']} ({item['catalog_source_id']}): {note}")
    else:
        lines.append("License review required: none")

    counts = report["provider_counts"]
    lines.append(
        "Provider counts: "
        f"species={counts['species']}, properties={counts['properties']}, reactions={counts['reactions']}"
    )
    return "\n".join(lines)


def _profile_for_factory(profile: dict[str, Any], registry_root: Path) -> dict[str, Any]:
    prepared = deepcopy(profile)
    prepared.setdefault("local_registry", {})["root"] = str(registry_root)
    return prepared


def _list(profile: dict[str, Any], key: str) -> list[str]:
    value = profile.get(key, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _source_is_configured_or_selected(profile: dict[str, Any], source: str) -> bool:
    if source == "internal_file":
        config = profile.get("internal_file")
        return isinstance(config, dict) and bool(config.get("root"))
    if source == "nist_snapshot":
        config = profile.get("nist_snapshot")
        return isinstance(config, dict) and bool(config.get("root"))
    if source == "argonne_atct_snapshot":
        config = profile.get("argonne_atct_snapshot")
        return isinstance(config, dict) and bool(config.get("files"))
    if source == "chemical_identity_snapshot":
        config = profile.get("chemical_identity_snapshot")
        return isinstance(config, dict) and bool(config.get("snapshot"))
    if source == "ion_reaction_table":
        config = profile.get("ion_reaction_table")
        return isinstance(config, dict) and bool(config.get("files"))
    return any(source in _list(profile, section) for section in SOURCE_SECTIONS)


def _load_source_catalog(source_catalog: str | Path | None, registry_root: Path) -> dict[str, dict[str, Any]]:
    candidates = []
    if source_catalog is not None:
        candidates.append(Path(source_catalog))
    candidates.extend(
        [
            registry_root.parent / "external_data" / "source_catalog.yaml",
            Path.cwd() / "external_data" / "source_catalog.yaml",
        ]
    )
    for path in candidates:
        if not path.exists():
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sources = payload.get("sources", []) if isinstance(payload, dict) else []
        if not isinstance(sources, list):
            return {}
        return {
            str(item.get("source_id")): item
            for item in sources
            if isinstance(item, dict) and item.get("source_id")
        }
    return {}


def _license_review_required(
    profile: dict[str, Any],
    configured_optional: list[str],
    catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not catalog:
        return []
    candidates = [
        *_list(profile, "active_sources"),
        *configured_optional,
        *_list(profile, "external_only_sources"),
    ]
    out = []
    seen = set()
    for source in candidates:
        catalog_id = SOURCE_CATALOG_ALIASES.get(source, source)
        item = catalog.get(catalog_id)
        if not item or not item.get("requires_license_review") or source in seen:
            continue
        out.append(
            {
                "source": source,
                "catalog_source_id": catalog_id,
                "redistribution_risk": item.get("redistribution_risk"),
                "notes": item.get("notes"),
            }
        )
        seen.add(source)
    return out


def _format_list(items: list[str]) -> str:
    return ", ".join(items) if items else "none"
