from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.preparation.property_candidates import (
    PROPERTY_NAMES,
    property_conflict,
    select_property_candidate,
    supported_property_candidates,
)


def enrich_species_properties(
    prepared_registry: Path,
    providers: list[Any],
    source_profile: dict[str, Any],
    species_ids: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Fill missing supported properties without replacing curated values."""

    prepared_registry = Path(prepared_registry)
    report = _empty_report(source_profile)
    species_dir = prepared_registry / "species"
    if not species_dir.exists():
        return report

    target_species_ids = set(species_ids) if species_ids is not None else None
    for path in sorted(species_dir.glob("*.yaml")):
        species = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        species_id = species.get("id") or path.stem
        if target_species_ids is not None and species_id not in target_species_ids:
            continue
        if _enrich_species(species, species_id, providers, source_profile, report):
            _write_species(path, species)

    _update_summary(report)
    return report


def _enrich_species(
    species: dict[str, Any],
    species_id: str,
    providers: list[Any],
    source_profile: dict[str, Any],
    report: dict[str, Any],
) -> bool:
    changed = False
    for property_name in PROPERTY_NAMES:
        supported, unsupported = supported_property_candidates(
            providers,
            species_id,
            property_name,
        )
        report["unresolved"].extend(unsupported)

        existing = _property_payload(species, property_name)
        if existing is not None and existing.get("value") is not None:
            conflict = property_conflict(
                species_id,
                property_name,
                existing,
                supported,
                source_profile,
            )
            if conflict is not None:
                report["property_conflicts"].append(conflict)
            continue

        candidate = select_property_candidate(supported, source_profile)
        if candidate is None:
            report["unresolved"].append(_missing_property_record(species_id, property_name))
            continue

        _apply_candidate(species, property_name, candidate)
        report["properties_filled"].append(
            _filled_property_record(species_id, property_name, candidate)
        )
        changed = True
    return changed


def _property_payload(
    species: dict[str, Any],
    property_name: str,
) -> dict[str, Any] | None:
    payload = species.get("properties", {}).get(property_name)
    return payload if isinstance(payload, dict) else None


def _apply_candidate(
    species: dict[str, Any],
    property_name: str,
    candidate: dict[str, Any],
) -> None:
    source_record = deepcopy(candidate.get("source_record"))
    species.setdefault("properties", {})[property_name] = {
        "value": candidate.get("value"),
        "unit": candidate.get("unit"),
        "source": candidate.get("source"),
        "source_record": source_record,
    }
    metadata = species.setdefault("metadata", {})
    metadata.setdefault("property_sources", {})[property_name] = deepcopy(source_record)


def _filled_property_record(
    species_id: str,
    property_name: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "species": species_id,
        "property": property_name,
        "value": candidate.get("value"),
        "unit": candidate.get("unit"),
        "source_record": deepcopy(candidate.get("source_record")),
    }


def _missing_property_record(species_id: str, property_name: str) -> dict[str, Any]:
    required_by = "dnt_readiness" if property_name == "collision_radius_A" else "prepare_enrichment"
    return {
        "kind": "missing_property",
        "species": species_id,
        "property": property_name,
        "reason": "no_supported_candidate",
        "required_by": required_by,
    }


def _empty_report(source_profile: dict[str, Any]) -> dict[str, Any]:
    return {
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


def _update_summary(report: dict[str, Any]) -> None:
    report["summary"] = {
        "n_properties_filled": len(report["properties_filled"]),
        "n_property_conflicts": len(report["property_conflicts"]),
        "n_unresolved": len(report["unresolved"]),
    }


def _write_species(path: Path, species: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(species, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
