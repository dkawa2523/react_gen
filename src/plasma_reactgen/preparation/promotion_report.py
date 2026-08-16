"""Bookkeeping helpers for the stable promotion report artifact."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.preparation.promotion_payloads import normalized_notes


def new_report(apply: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registry_mutated": False,
        "dry_run": not apply,
        "promoted_species": [],
        "promoted_channels": [],
        "rejected": [],
        "conflicts": [],
        "summary": {},
    }


def finish_report(report: dict[str, Any]) -> None:
    report["summary"] = {
        "n_promoted_species": len(report["promoted_species"]),
        "n_promoted_channels": len(report["promoted_channels"]),
        "n_rejected": len(report["rejected"]),
        "n_conflicts": len(report["conflicts"]),
    }


def promotion_item(
    kind: str,
    item_id: str,
    source: Path,
    target: Path,
    apply: bool,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": item_id,
        "source": str(source),
        "target": str(target),
        "dry_run": not apply,
    }


def record_rejection(report: dict[str, Any], decision: dict[str, Any]) -> None:
    report["rejected"].append(
        {
            "kind": decision.get("kind"),
            "id": decision.get("id"),
            "reason": "rejected_by_decision",
            "notes": normalized_notes(decision.get("notes")),
        }
    )


def record_conflict(
    report: dict[str, Any],
    decision: dict[str, Any],
    reason: str,
    **extra: Any,
) -> None:
    report["conflicts"].append(
        {
            "kind": decision.get("kind"),
            "id": decision.get("id"),
            "reason": reason,
            **extra,
        }
    )


__all__ = [
    "finish_report",
    "new_report",
    "promotion_item",
    "record_conflict",
    "record_rejection",
]
