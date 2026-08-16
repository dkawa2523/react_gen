"""Orchestrate explicit promotion from prepared data into the registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.preparation.promotion_items import (
    promote_reaction_channel,
    promote_species,
)
from plasma_reactgen.preparation.promotion_report import (
    finish_report,
    new_report,
    record_conflict,
    record_rejection,
)
from plasma_reactgen.preparation.promotion_repository import (
    load_decisions,
    write_yaml,
)


def promote_reviewed_registry(
    prepared_registry: Path,
    registry: Path,
    decision_file: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    registry = Path(registry)
    report = new_report(apply)
    for decision in load_decisions(Path(decision_file)):
        mutated = _process_decision(
            decision,
            prepared_registry,
            registry,
            report,
            apply=apply,
        )
        report["registry_mutated"] = bool(report["registry_mutated"] or mutated)
    finish_report(report)
    write_yaml(prepared_registry.parent / "promote_report.yaml", report)
    return report


def _process_decision(
    decision: Any,
    prepared_registry: Path,
    registry: Path,
    report: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    if not isinstance(decision, dict):
        record_conflict(
            report,
            {"kind": "decision", "id": None},
            "invalid_decision",
        )
        return False
    action = decision.get("action")
    if action == "reject":
        record_rejection(report, decision)
        return False
    if action != "promote":
        record_conflict(report, decision, "unsupported_action")
        return False
    if decision.get("kind") == "species":
        return promote_species(
            prepared_registry,
            registry,
            decision,
            report,
            apply=apply,
        )
    if decision.get("kind") == "reaction_channel":
        return promote_reaction_channel(
            prepared_registry,
            registry,
            decision,
            report,
            apply=apply,
        )
    record_conflict(report, decision, "unsupported_kind")
    return False


__all__ = ["promote_reviewed_registry"]
