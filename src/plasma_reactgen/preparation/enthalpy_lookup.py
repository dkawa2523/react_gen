from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

PROPERTY_NAME = "enthalpy_formation_eV"
SUPPORTED_UNIT = "eV"


def load_local_enthalpies(prepared_registry: Path) -> dict[str, dict[str, Any]]:
    species_dir = prepared_registry / "species"
    if not species_dir.exists():
        return {}

    enthalpies: dict[str, dict[str, Any]] = {}
    seen_species: set[str] = set()
    for path in sorted(species_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        species_id = payload.get("id")
        if not species_id or species_id in seen_species:
            continue
        seen_species.add(species_id)
        candidate = _local_candidate(str(species_id), payload)
        if candidate is not None:
            enthalpies[str(species_id)] = candidate
    return enthalpies


def resolve_enthalpies(
    species_ids: list[str],
    local_enthalpies: dict[str, dict[str, Any]],
    property_providers: list[Any],
) -> dict[str, dict[str, Any]]:
    resolved = {
        species_id: local_enthalpies[species_id]
        for species_id in species_ids
        if species_id in local_enthalpies
    }
    for species_id in species_ids:
        if species_id in resolved:
            continue
        candidate = _provider_enthalpy(species_id, property_providers)
        if candidate is not None:
            resolved[species_id] = candidate
    return resolved


def _local_candidate(
    species_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    prop = payload.get("properties", {}).get(PROPERTY_NAME)
    if not isinstance(prop, dict):
        return None
    if prop.get("value") is None or prop.get("unit") != SUPPORTED_UNIT:
        return None
    return {
        "species": species_id,
        "property": PROPERTY_NAME,
        "value": prop.get("value"),
        "unit": prop.get("unit"),
        "source_record": deepcopy(prop.get("source_record") or prop.get("source")),
    }


def _provider_enthalpy(
    species_id: str,
    property_providers: list[Any],
) -> dict[str, Any] | None:
    for provider in property_providers:
        if not hasattr(provider, "find_properties"):
            continue
        candidates = provider.find_properties(species_id, [PROPERTY_NAME])
        candidate = _first_supported_enthalpy(candidates)
        if candidate is not None:
            return candidate
    return None


def _first_supported_enthalpy(
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("property") != PROPERTY_NAME:
            continue
        if candidate.get("unit") == SUPPORTED_UNIT and candidate.get("value") is not None:
            return deepcopy(candidate)
    return None
