"""Promote reviewed species and reaction-channel items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.domain.identifiers import to_file_key
from plasma_reactgen.preparation.promotion_payloads import (
    channel_payload,
    new_pair_payload,
    pair_from_decision,
    species_payload,
)
from plasma_reactgen.preparation.promotion_report import (
    promotion_item,
    record_conflict,
)
from plasma_reactgen.preparation.promotion_repository import (
    PairRecord,
    find_pair_file,
    find_prepared_channel,
    find_species_file,
    load_yaml,
    reaction_pair_path,
    write_yaml,
)


def promote_species(
    prepared_registry: Path,
    registry: Path,
    decision: dict[str, Any],
    report: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    source = _species_source(prepared_registry, decision, report)
    if source is None:
        return False
    species_id, source_path, source_payload = source
    registry_existing = find_species_file(registry, species_id)
    if registry_existing is not None:
        record_conflict(
            report,
            decision,
            "curated_species_exists",
            existing=str(registry_existing[0]),
            source=str(source_path),
        )
        return False

    payload = species_payload(source_payload, decision)
    target_id = str(payload.get("id") or species_id)
    target_path = registry / "species" / f"{to_file_key(target_id)}.yaml"
    if target_path.exists():
        record_conflict(
            report,
            decision,
            "target_species_file_exists",
            existing=str(target_path),
            source=str(source_path),
        )
        return False
    report["promoted_species"].append(
        promotion_item("species", species_id, source_path, target_path, apply)
    )
    if apply:
        write_yaml(target_path, payload)
    return apply


def promote_reaction_channel(
    prepared_registry: Path,
    registry: Path,
    decision: dict[str, Any],
    report: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    source = _reaction_source(prepared_registry, decision, report)
    if source is None:
        return False
    channel_id, pair, source_path, channel = source
    target_path = find_pair_file(registry, pair) or reaction_pair_path(registry, pair)
    target_payload = load_yaml(target_path) if target_path.exists() else new_pair_payload(pair)
    if _has_channel(target_payload, channel_id):
        record_conflict(
            report,
            decision,
            "curated_channel_exists",
            existing=str(target_path),
            source=str(source_path),
            pair=pair,
        )
        return False
    item = promotion_item(
        "reaction_channel",
        channel_id,
        source_path,
        target_path,
        apply,
    )
    item["pair"] = pair
    report["promoted_channels"].append(item)
    if apply:
        target_payload.setdefault("channels", []).append(channel_payload(channel, decision))
        write_yaml(target_path, target_payload)
    return apply


def _species_source(
    prepared_registry: Path,
    decision: dict[str, Any],
    report: dict[str, Any],
) -> tuple[str, Path, dict[str, Any]] | None:
    species_id = str(decision.get("id") or "")
    if not species_id:
        record_conflict(report, decision, "missing_species_id")
        return None
    source = find_species_file(prepared_registry, species_id)
    if source is None:
        record_conflict(report, decision, "prepared_species_not_found")
        return None
    return species_id, *source


def _reaction_source(
    prepared_registry: Path,
    decision: dict[str, Any],
    report: dict[str, Any],
) -> tuple[str, PairRecord, Path, dict[str, Any]] | None:
    channel_id = str(decision.get("id") or "")
    pair = pair_from_decision(decision)
    if not channel_id:
        record_conflict(report, decision, "missing_channel_id")
        return None
    if pair is None:
        record_conflict(report, decision, "missing_pair")
        return None
    found = find_prepared_channel(prepared_registry, channel_id, pair)
    if found is None:
        record_conflict(report, decision, "prepared_channel_not_found", pair=pair)
        return None
    source_path, channel = found
    return channel_id, pair, source_path, channel


def _has_channel(payload: dict[str, Any], channel_id: str) -> bool:
    channels = payload.get("channels", [])
    return isinstance(channels, list) and any(
        isinstance(item, dict) and str(item.get("id")) == channel_id for item in channels
    )


__all__ = ["promote_reaction_channel", "promote_species"]
