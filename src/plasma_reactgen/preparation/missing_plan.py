from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.missing_actions import (
    ACTION_ORDER,
    action_for_missing_item,
    priority_for_action,
)
from plasma_reactgen.preparation.input_report_reader import load_missing_data

COMMAND_HINTS = {
    "seed_species": "Add reviewed species YAML under prepared_registry/species/.",
    "enrich_properties": "Run prepare/enrich with configured local property providers.",
    "import_cross_sections": (
        "reactgen import-cross-sections INPUT_FILE --workspace WORKSPACE "
        "--reaction-id REACTION_ID --target TARGET"
    ),
    "review_reaction_energetics": (
        "Review deltaE_products_minus_reactants_eV in prepared_registry reaction channels."
    ),
    "manual_review": "Inspect missing_data.yaml and decide the next reviewed action.",
}


def build_missing_plan(outputs_or_missing_data: Path) -> dict[str, Any]:
    _, _, missing_items = load_missing_data(outputs_or_missing_data)

    actions = _group_actions(missing_items)
    return {
        "schema_version": 1,
        "summary": {
            "total_missing_items": len(missing_items),
            "suggested_actions": len(actions),
        },
        "actions": actions,
    }


def write_missing_plan(outputs_or_missing_data: Path, output: Path) -> dict[str, Any]:
    plan = build_missing_plan(outputs_or_missing_data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(plan, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return plan


def _group_actions(missing_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for action in ACTION_ORDER:
        grouped[action] = {
            "action": action,
            "priority": priority_for_action(action),
            "subjects": [],
            "command_hint": COMMAND_HINTS[action],
            "notes": [],
        }

    seen_subjects: dict[str, set[str]] = {action: set() for action in ACTION_ORDER}
    for item in missing_items:
        action = action_for_missing_item(item)
        subject = str(item.get("subject_id") or item.get("id") or "unknown")
        if subject not in seen_subjects[action]:
            grouped[action]["subjects"].append(subject)
            seen_subjects[action].add(subject)

    return [grouped[action] for action in ACTION_ORDER if grouped[action]["subjects"]]
