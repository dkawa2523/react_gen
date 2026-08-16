"""Pure decision and payload transformations for registry promotion."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from plasma_reactgen.preparation.promotion_repository import PairRecord


def pair_from_decision(decision: dict[str, Any]) -> PairRecord | None:
    pair = decision.get("pair")
    required = ("family", "projectile", "target")
    if not isinstance(pair, dict) or any(not pair.get(key) for key in required):
        return None
    return {key: str(pair[key]) for key in required}


def species_payload(
    payload: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    output = deepcopy(payload)
    output.setdefault("schema_version", 1)
    metadata = output.setdefault("metadata", {})
    target_status = decision.get("target_status")
    if target_status:
        metadata["status"] = target_status
    append_notes(metadata, decision.get("notes"))
    return output


def channel_payload(
    channel: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    output = deepcopy(channel)
    for internal_key in ("schema_version", "kind", "pair"):
        output.pop(internal_key, None)
    target_status = decision.get("target_status")
    if target_status:
        output["status"] = target_status
    append_notes(output, decision.get("notes"))
    return output


def new_pair_payload(pair: PairRecord) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pair": deepcopy(pair),
        "channels": [],
        "metadata": {
            "status": "curated",
            "notes": ["Created by promote workflow from reviewed prepared/candidate data."],
        },
    }


def normalized_notes(notes: Any) -> list[Any]:
    if isinstance(notes, str):
        return [notes]
    return notes if isinstance(notes, list) else []


def append_notes(payload: dict[str, Any], notes: Any) -> None:
    new_notes = normalized_notes(notes)
    if not new_notes:
        return
    existing = payload.setdefault("notes", [])
    if not isinstance(existing, list):
        existing = [existing]
        payload["notes"] = existing
    existing.extend(str(note) for note in new_notes)


__all__ = [
    "channel_payload",
    "new_pair_payload",
    "normalized_notes",
    "pair_from_decision",
    "species_payload",
]
