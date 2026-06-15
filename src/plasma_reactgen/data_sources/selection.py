from __future__ import annotations

from typing import Any


DEFAULT_STATUS_ORDER = [
    "curated",
    "literature_supported",
    "imported",
    "estimated",
    "inferred",
    "draft",
    "deprecated",
]


def status_rank(status: str, profile: dict) -> int:
    order = _status_order(profile)
    try:
        return order.index(str(status))
    except ValueError:
        return len(order)


def source_rank(source_name: str, category: str, profile: dict) -> int:
    sources = profile.get(category, [])
    if not isinstance(sources, list):
        return 10_000
    try:
        return [str(source) for source in sources].index(str(source_name))
    except ValueError:
        return len(sources)


def select_first_candidate(
    candidates: list[dict],
    category: str,
    profile: dict,
) -> dict | None:
    if not candidates:
        return None
    ranked = [
        (
            source_rank(_candidate_source_name(candidate, category, profile), category, profile),
            status_rank(str(candidate.get("status", "imported")), profile),
            index,
            candidate,
        )
        for index, candidate in enumerate(candidates)
        if isinstance(candidate, dict)
    ]
    if not ranked:
        return None
    return min(ranked, key=lambda item: item[:3])[3]


def _status_order(profile: dict) -> list[str]:
    policy = profile.get("policy", {})
    preferred = policy.get("prefer_status", []) if isinstance(policy, dict) else []
    order: list[str] = []
    for status in [*preferred, *DEFAULT_STATUS_ORDER]:
        value = str(status)
        if value not in order:
            order.append(value)
    return order


def _candidate_source_name(candidate: dict[str, Any], category: str, profile: dict) -> str:
    if candidate.get("source_name"):
        return str(candidate["source_name"])

    source = candidate.get("source")
    if isinstance(source, str) and source in set(str(item) for item in profile.get(category, [])):
        return source
    if isinstance(source, dict):
        mapped = _source_record_name(source, category)
        if mapped:
            return mapped

    source_record = candidate.get("source_record")
    if isinstance(source_record, dict):
        mapped = _source_record_name(source_record, category)
        if mapped:
            return mapped

    return ""


def _source_record_name(source_record: dict[str, Any], category: str) -> str | None:
    for key in ("source_name", "provider", "name"):
        if source_record.get(key):
            return str(source_record[key])

    source_type = str(source_record.get("source_type") or "")
    database = str(source_record.get("database") or "")
    if source_type == "local_registry":
        return "local_registry"
    if source_type == "local_assets":
        return "local_assets"
    if source_type == "internal_file_db":
        return {
            "species_identity": "internal_species_db",
            "properties": "internal_property_db",
            "electron_cross_sections": "internal_cross_section_db",
            "ion_neutral_reactions": "internal_reaction_db",
            "electron_reactions": "internal_reaction_db",
        }.get(category, "internal_file")
    if source_type == "public_database_snapshot":
        lowered = database.lower()
        if "nist" in lowered:
            return "nist_snapshot"
        if "lxcat" in lowered:
            return "lxcat_offline"
    if source_type == "python_package" and database == "chemicals":
        return str(source_record.get("source_name") or "chemicals_optional")
    if source_type == "local_snapshot" and "ion" in database.lower():
        return "ion_reaction_table"
    return source_type or None
