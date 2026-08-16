from __future__ import annotations

from typing import Any


ACTION_ORDER = (
    "seed_species",
    "enrich_properties",
    "import_cross_sections",
    "review_reaction_energetics",
    "manual_review",
)

PROPERTY_FIELDS = {
    "polarizability_A3",
    "dipole_moment_D",
    "collision_radius_A",
    "enthalpy_formation_eV",
}


def action_for_missing_field(field: str) -> str:
    if field == "registry/species":
        return "seed_species"
    if field in {"data.cross_section", "data.cross_section.path"}:
        return "import_cross_sections"
    if field == "deltaE_products_minus_reactants_eV":
        return "review_reaction_energetics"
    if field.rsplit(".", 1)[-1] in PROPERTY_FIELDS:
        return "enrich_properties"
    return "manual_review"


def action_for_missing_item(item: dict[str, Any]) -> str:
    return action_for_missing_field(str(item.get("field") or ""))


def priority_for_action(action: str) -> str:
    if action in {"seed_species", "enrich_properties", "import_cross_sections"}:
        return "high"
    if action == "review_reaction_energetics":
        return "medium"
    return "low"


def priority_sort(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)
