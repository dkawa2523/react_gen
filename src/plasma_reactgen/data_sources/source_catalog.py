from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.data_sources.source_configuration import profile_list

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


def load_source_catalog(
    source_catalog: str | Path | None,
    registry_root: Path,
) -> dict[str, dict[str, Any]]:
    for path in _catalog_candidates(source_catalog, registry_root):
        if path.exists():
            return _read_catalog(path)
    return {}


def license_review_items(
    profile: dict[str, Any],
    configured_optional: list[str],
    catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [
        *profile_list(profile, "active_sources"),
        *configured_optional,
        *profile_list(profile, "external_only_sources"),
    ]
    review_items = []
    seen = set()
    for source in candidates:
        item = _review_item(source, catalog)
        if item is not None and source not in seen:
            review_items.append(item)
            seen.add(source)
    return review_items


def _catalog_candidates(source_catalog: str | Path | None, registry_root: Path) -> list[Path]:
    explicit = [Path(source_catalog)] if source_catalog is not None else []
    return [
        *explicit,
        registry_root.parent / "external_data" / "source_catalog.yaml",
        Path.cwd() / "external_data" / "source_catalog.yaml",
    ]


def _read_catalog(path: Path) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    if not isinstance(sources, list):
        return {}
    return {
        str(item["source_id"]): item
        for item in sources
        if isinstance(item, dict) and item.get("source_id")
    }


def _review_item(
    source: str,
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    catalog_id = SOURCE_CATALOG_ALIASES.get(source, source)
    item = catalog.get(catalog_id)
    if not item or not item.get("requires_license_review"):
        return None
    return {
        "source": source,
        "catalog_source_id": catalog_id,
        "redistribution_risk": item.get("redistribution_risk"),
        "notes": item.get("notes"),
    }
