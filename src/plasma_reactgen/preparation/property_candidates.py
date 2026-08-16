from __future__ import annotations

from copy import deepcopy
from typing import Any

from plasma_reactgen.data_sources.selection import select_first_candidate

PROPERTY_NAMES = [
    "mass_amu",
    "ionization_energy_eV",
    "electron_affinity_eV",
    "enthalpy_formation_eV",
    "dipole_moment_D",
    "polarizability_A3",
    "collision_radius_A",
]

SUPPORTED_UNITS = {
    "mass_amu": "amu",
    "ionization_energy_eV": "eV",
    "electron_affinity_eV": "eV",
    "enthalpy_formation_eV": "eV",
    "dipole_moment_D": "D",
    "polarizability_A3": "A3",
    "collision_radius_A": "A",
}


def supported_property_candidates(
    providers: list[Any],
    species_id: str,
    property_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _provider_candidates(providers, species_id, property_name)
    return _split_supported_candidates(candidates, property_name)


def select_property_candidate(
    candidates: list[dict[str, Any]],
    source_profile: dict[str, Any],
) -> dict[str, Any] | None:
    return select_first_candidate(candidates, "properties", source_profile)


def property_conflict(
    species_id: str,
    property_name: str,
    existing: dict[str, Any],
    candidates: list[dict[str, Any]],
    source_profile: dict[str, Any],
) -> dict[str, Any] | None:
    existing_value = existing.get("value")
    conflicting = [
        candidate for candidate in candidates if candidate.get("value") != existing_value
    ]
    candidate = select_property_candidate(conflicting, source_profile)
    if candidate is None:
        return None
    return {
        "kind": "property_conflict",
        "species": species_id,
        "property": property_name,
        "existing_value": existing_value,
        "candidate_value": candidate.get("value"),
        "candidate_source": deepcopy(candidate.get("source_record")),
        "action": "manual_review",
    }


def _provider_candidates(
    providers: list[Any],
    species_id: str,
    property_name: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for provider in providers:
        if not hasattr(provider, "find_properties"):
            continue
        candidates.extend(
            candidate
            for candidate in provider.find_properties(species_id, [property_name])
            if isinstance(candidate, dict)
        )
    return candidates


def _split_supported_candidates(
    candidates: list[dict[str, Any]],
    property_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supported: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    expected_unit = SUPPORTED_UNITS[property_name]
    for candidate in candidates:
        if candidate.get("value") is None:
            continue
        if candidate.get("unit") == expected_unit:
            supported.append(candidate)
        else:
            unresolved.append(_unsupported_unit_record(candidate, property_name, expected_unit))
    return supported, unresolved


def _unsupported_unit_record(
    candidate: dict[str, Any],
    property_name: str,
    expected_unit: str,
) -> dict[str, Any]:
    return {
        "kind": "unsupported_unit",
        "species": candidate.get("species"),
        "property": property_name,
        "candidate_unit": candidate.get("unit"),
        "expected_unit": expected_unit,
        "candidate_source": deepcopy(candidate.get("source_record")),
    }
