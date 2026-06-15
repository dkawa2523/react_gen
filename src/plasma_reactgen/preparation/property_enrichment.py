from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

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


def enrich_species_properties(
    prepared_registry: Path,
    providers: list[Any],
    source_profile: dict[str, Any],
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    report: dict[str, Any] = {
        "schema_version": 1,
        "source_profile": source_profile.get("name", "custom"),
        "properties_filled": [],
        "property_conflicts": [],
        "unresolved": [],
        "summary": {
            "n_properties_filled": 0,
            "n_property_conflicts": 0,
            "n_unresolved": 0,
        },
    }

    species_dir = prepared_registry / "species"
    if not species_dir.exists():
        return report

    for path in sorted(species_dir.glob("*.yaml")):
        species = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        species_id = species.get("id") or path.stem
        changed = False
        for property_name in PROPERTY_NAMES:
            existing = _property_payload(species, property_name)
            candidates = _provider_candidates(providers, species_id, property_name)
            supported, unsupported = _split_supported_candidates(candidates, property_name)
            report["unresolved"].extend(unsupported)

            if _has_non_null_value(existing):
                conflict = _conflict_record(species_id, property_name, existing, supported, source_profile)
                if conflict:
                    report["property_conflicts"].append(conflict)
                continue

            candidate = select_first_candidate(supported, "properties", source_profile)
            if candidate is None:
                report["unresolved"].append(
                    {
                        "kind": "missing_property",
                        "species": species_id,
                        "property": property_name,
                        "reason": "no_supported_candidate",
                        "required_by": "dnt_readiness" if property_name == "collision_radius_A" else "prepare_enrichment",
                    }
                )
                continue

            _apply_candidate(species, property_name, candidate)
            changed = True
            report["properties_filled"].append(
                {
                    "species": species_id,
                    "property": property_name,
                    "value": candidate.get("value"),
                    "unit": candidate.get("unit"),
                    "source_record": deepcopy(candidate.get("source_record")),
                }
            )

        if changed:
            path.write_text(
                yaml.safe_dump(species, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

    report["summary"]["n_properties_filled"] = len(report["properties_filled"])
    report["summary"]["n_property_conflicts"] = len(report["property_conflicts"])
    report["summary"]["n_unresolved"] = len(report["unresolved"])
    return report


def _provider_candidates(providers: list[Any], species_id: str, property_name: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for provider in providers:
        if not hasattr(provider, "find_properties"):
            continue
        for candidate in provider.find_properties(species_id, [property_name]):
            if isinstance(candidate, dict):
                candidates.append(candidate)
    return candidates


def _split_supported_candidates(
    candidates: list[dict[str, Any]],
    property_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supported: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    expected_unit = SUPPORTED_UNITS[property_name]
    for candidate in candidates:
        unit = candidate.get("unit")
        if candidate.get("value") is None:
            continue
        if unit == expected_unit:
            supported.append(candidate)
        else:
            unresolved.append(
                {
                    "kind": "unsupported_unit",
                    "species": candidate.get("species"),
                    "property": property_name,
                    "candidate_unit": unit,
                    "expected_unit": expected_unit,
                    "candidate_source": deepcopy(candidate.get("source_record")),
                }
            )
    return supported, unresolved


def _property_payload(species: dict[str, Any], property_name: str) -> dict[str, Any] | None:
    payload = species.get("properties", {}).get(property_name)
    return payload if isinstance(payload, dict) else None


def _has_non_null_value(payload: dict[str, Any] | None) -> bool:
    return payload is not None and payload.get("value") is not None


def _conflict_record(
    species_id: str,
    property_name: str,
    existing: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    source_profile: dict[str, Any],
) -> dict[str, Any] | None:
    if existing is None:
        return None
    existing_value = existing.get("value")
    conflicting = [
        candidate
        for candidate in candidates
        if candidate.get("value") is not None and candidate.get("value") != existing_value
    ]
    candidate = select_first_candidate(conflicting, "properties", source_profile)
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


def _apply_candidate(species: dict[str, Any], property_name: str, candidate: dict[str, Any]) -> None:
    species.setdefault("properties", {})[property_name] = {
        "value": candidate.get("value"),
        "unit": candidate.get("unit"),
        "source": candidate.get("source"),
        "source_record": deepcopy(candidate.get("source_record")),
    }
    metadata = species.setdefault("metadata", {})
    metadata.setdefault("property_sources", {})[property_name] = deepcopy(candidate.get("source_record"))
