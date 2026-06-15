from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml


ACTION_ORDER = [
    "seed_species",
    "enrich_properties",
    "import_cross_sections",
    "review_reaction_energetics",
    "manual_review",
]

COMMAND_HINTS = {
    "seed_species": "Add reviewed species YAML under prepared_registry/species/.",
    "enrich_properties": "Run prepare/enrich with configured local property providers.",
    "import_cross_sections": "reactgen import-cross-sections INPUT_FILE --workspace WORKSPACE --reaction-id REACTION_ID --target TARGET",
    "review_reaction_energetics": "Review deltaE_products_minus_reactants_eV in prepared_registry reaction channels.",
    "manual_review": "Inspect missing_data.yaml and decide the next reviewed action.",
}

PROPERTY_FIELDS = {
    "target.polarizability_A3",
    "target.dipole_moment_D",
    "target.collision_radius_A",
    "polarizability_A3",
    "dipole_moment_D",
    "collision_radius_A",
    "enthalpy_formation_eV",
}


def build_missing_plan(outputs_or_missing_data: Path) -> dict[str, Any]:
    missing_path = resolve_missing_data_path(outputs_or_missing_data)
    payload = _read_yaml(missing_path)
    missing_items = _missing_items(payload)

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


def resolve_missing_data_path(outputs_or_missing_data: Path) -> Path:
    path = Path(outputs_or_missing_data)
    if path.is_dir():
        path = path / "missing_data.yaml"
    if not path.exists():
        raise FileNotFoundError(f"missing_data.yaml not found: {path}")
    return path


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed missing-data YAML: {path}") from exc


def _missing_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("missing_data", [])
    else:
        raise ValueError("missing-data payload must be a mapping or a list")
    if not isinstance(items, list):
        raise ValueError("missing_data must be a list")
    return [item for item in items if isinstance(item, dict)]


def _group_actions(missing_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for action in ACTION_ORDER:
        grouped[action] = {
            "action": action,
            "priority": _priority_for_action(action),
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


def action_for_missing_item(item: dict[str, Any]) -> str:
    field = str(item.get("field") or "")
    if field == "registry/species":
        return "seed_species"
    if field in {"data.cross_section", "data.cross_section.path"}:
        return "import_cross_sections"
    if field == "deltaE_products_minus_reactants_eV":
        return "review_reaction_energetics"
    if field in PROPERTY_FIELDS:
        return "enrich_properties"
    if field.startswith(("target.", "neutral.", "projectile.", "ion.")):
        if field.rsplit(".", 1)[-1] in PROPERTY_FIELDS:
            return "enrich_properties"
    return "manual_review"


def _priority_for_action(action: str) -> str:
    if action in {"seed_species", "enrich_properties", "import_cross_sections"}:
        return "high"
    if action == "review_reaction_energetics":
        return "medium"
    return "low"
