from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


def merge_identity_candidate(
    species: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    """Merge non-destructive identity fields and return manual-review conflicts."""

    metadata = species.setdefault("metadata", {})
    changed = any(
        (
            _merge_unique_values(metadata, "aliases", candidate.get("aliases", [])),
            _fill_missing_identifiers(metadata, candidate.get("identifiers")),
            _merge_unique_values(
                metadata,
                "ontology_tags",
                candidate.get("ontology_tags", []),
            ),
            _merge_source_records(metadata, candidate.get("source_records", [])),
        )
    )
    formula_changed, conflicts = _merge_formula(species, candidate.get("formula"))
    return changed or formula_changed, conflicts


def _merge_unique_values(
    metadata: dict[str, Any],
    field_name: str,
    candidate_values: list[Any],
) -> bool:
    existing = metadata.get(field_name, [])
    merged = _unique([*existing, *candidate_values])
    if merged == existing:
        return False
    metadata[field_name] = merged
    return True


def _fill_missing_identifiers(
    metadata: dict[str, Any],
    candidate_identifiers: Any,
) -> bool:
    identifiers = metadata.setdefault("identifiers", {})
    if not isinstance(candidate_identifiers, dict):
        return False
    changed = False
    for key, value in candidate_identifiers.items():
        if value is not None and identifiers.get(key) in (None, ""):
            identifiers[key] = value
            changed = True
    return changed


def _merge_source_records(
    metadata: dict[str, Any],
    candidate_records: list[Any],
) -> bool:
    source_records = metadata.setdefault("identity_source_records", [])
    additions = [
        deepcopy(record)
        for record in candidate_records
        if isinstance(record, dict) and record not in source_records
    ]
    source_records.extend(additions)
    return bool(additions)


def _merge_formula(
    species: dict[str, Any],
    candidate_formula: Any,
) -> tuple[bool, list[dict[str, Any]]]:
    if not candidate_formula:
        return False, []

    formula = str(candidate_formula)
    existing_formula = species.get("formula")
    if existing_formula in (None, ""):
        species["formula"] = formula
        formula_changed = True
    else:
        formula_changed = False

    conflicts = _formula_conflicts(species, formula, existing_formula)
    return formula_changed, conflicts


def _formula_conflicts(
    species: dict[str, Any],
    candidate_formula: str,
    existing_formula: Any,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if existing_formula not in (None, "", candidate_formula):
        conflicts.append(
            {
                "kind": "formula_conflict",
                "species": species.get("id"),
                "existing_formula": existing_formula,
                "candidate_formula": candidate_formula,
                "action": "manual_review",
            }
        )

    candidate_composition = _composition_from_formula(candidate_formula)
    existing_composition = species.get("composition")
    if (
        candidate_composition
        and existing_composition
        and existing_composition != candidate_composition
    ):
        conflicts.append(
            {
                "kind": "composition_conflict",
                "species": species.get("id"),
                "existing_composition": existing_composition,
                "candidate_composition": candidate_composition,
                "action": "manual_review",
            }
        )
    return conflicts


def _unique(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        item = str(value)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _composition_from_formula(formula: str) -> dict[str, int]:
    composition: dict[str, int] = {}
    for element, count_text in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        composition[element] = composition.get(element, 0) + int(count_text or "1")
    return composition
