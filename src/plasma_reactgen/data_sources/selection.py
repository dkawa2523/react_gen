from __future__ import annotations

from typing import Any

from plasma_reactgen.data_sources.source_identity import source_name_from_record

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
    configured_sources = {str(item) for item in profile.get(category, [])}
    if isinstance(source, str) and source in configured_sources:
        return source
    for source_record in (source, candidate.get("source_record")):
        if not isinstance(source_record, dict):
            continue
        mapped = source_name_from_record(source_record, category)
        if mapped:
            return mapped
    return ""
