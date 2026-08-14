"""Seed, project, and maintain species in a prepared registry workspace."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.identifiers import to_file_key
from plasma_reactgen.domain.models import PropertyValue, Species
from plasma_reactgen.infrastructure.file_registry import FileRegistry

_PREPARED_SOURCE_TYPES = {
    "internal_file_db",
    "public_database_snapshot",
    "python_package",
}


def seed_species(
    gases: list[str],
    registry: FileRegistry,
    species_providers: list[Any],
    report: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    prepared: dict[str, dict[str, Any]] = {}
    for query in gases:
        local_species = registry.get_species(query)
        if local_species is not None:
            prepared[query] = _registry_species_payload(local_species)
            continue
        candidate = _first_species_candidate(query, species_providers)
        if candidate is None:
            continue
        species = _candidate_species_payload(candidate)
        prepared[species["id"]] = species
        report["summary"]["n_species_written"] += 1
        report["entries"].append({"kind": "species", "id": species["id"]})
    return prepared


def write_prepared_species(
    output_dir: Path,
    prepared_species: dict[str, dict[str, Any]],
    *,
    has_property_providers: bool,
) -> None:
    for species_id, species in prepared_species.items():
        if has_prepared_provenance(species) or has_property_providers:
            write_yaml(
                output_dir / "species" / f"{to_file_key(species_id)}.yaml",
                species,
            )


def remove_unmodified_local_overlays(output_dir: Path) -> None:
    species_dir = output_dir / "species"
    if not species_dir.exists():
        return
    for path in sorted(species_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict) and has_prepared_provenance(payload):
            continue
        path.unlink()


def has_prepared_provenance(species: dict[str, Any]) -> bool:
    metadata = species.get("metadata")
    if isinstance(metadata, dict) and _has_prepared_source(metadata.get("source_record")):
        return True
    properties = species.get("properties", {})
    if not isinstance(properties, dict):
        return False
    return any(
        isinstance(prop, dict) and _has_prepared_source(prop.get("source_record"))
        for prop in properties.values()
    )


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _first_species_candidate(
    query: str,
    species_providers: list[Any],
) -> dict[str, Any] | None:
    for provider in species_providers:
        candidates = provider.find_species(query)
        if candidates:
            return candidates[0]
    return None


def _candidate_species_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    species_id = candidate["id"]
    properties = deepcopy(candidate.get("properties", {}))
    if candidate.get("molecular_weight_amu") is not None:
        properties.setdefault(
            "mass_amu",
            {
                "value": candidate["molecular_weight_amu"],
                "unit": "amu",
                "source": "chemicals molecular weight databank",
                "source_record": deepcopy(candidate.get("source_record")),
            },
        )
    metadata = _candidate_metadata(candidate)
    return {
        "schema_version": 1,
        "id": species_id,
        "display_name": candidate.get("display_name", species_id),
        "formula": candidate.get("formula"),
        "composition": deepcopy(candidate.get("composition", {})),
        "charge": int(candidate.get("charge", 0)),
        "classes": list(candidate.get("classes", [])),
        "state": deepcopy(candidate.get("state", {})),
        "properties": properties,
        "metadata": metadata,
    }


def _candidate_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "status": candidate.get("status", "imported"),
        "source_record": deepcopy(candidate.get("source_record")),
        "notes": ["Prepared from enrichment source data; curated registry was not mutated."],
    }
    if candidate.get("cas"):
        metadata["cas"] = candidate["cas"]
    if candidate.get("aliases"):
        metadata["aliases"] = list(candidate["aliases"])
    return metadata


def _registry_species_payload(species: Species) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": species.id,
        "display_name": species.id,
        "composition": deepcopy(species.composition),
        "charge": species.charge,
        "classes": sorted(species.classes),
        "state": deepcopy(species.state),
        "properties": {
            name: _property_value_payload(prop) for name, prop in sorted(species.properties.items())
        },
        "metadata": {
            "status": species.status,
            "notes": ["Prepared overlay; curated registry was not mutated."],
        },
    }


def _property_value_payload(prop: PropertyValue) -> dict[str, Any]:
    payload = {"value": prop.value, "unit": prop.unit, "source": prop.source}
    if prop.source_record is not None:
        payload["source_record"] = deepcopy(prop.source_record)
    return payload


def _has_prepared_source(source_record: Any) -> bool:
    return (
        isinstance(source_record, dict)
        and source_record.get("source_type") in _PREPARED_SOURCE_TYPES
    )


__all__ = [
    "has_prepared_provenance",
    "remove_unmodified_local_overlays",
    "seed_species",
    "write_prepared_species",
    "write_yaml",
]
