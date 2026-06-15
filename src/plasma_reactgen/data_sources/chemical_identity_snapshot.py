from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import re

import yaml


class ChemicalIdentitySnapshotProvider:
    """Read local chemical identity snapshots for prepare/enrich metadata."""

    def __init__(self, snapshot: str | Path):
        self.snapshot = Path(snapshot)
        self.records = _load_records(self.snapshot)

    def find_species(self, species_id: str) -> list[dict[str, Any]]:
        matches = []
        for record in self.records:
            if _matches(record, species_id):
                matches.append(deepcopy(record))
        return matches

    def status(self) -> dict[str, Any]:
        return {
            "available": self.snapshot.exists(),
            "source": "chemical_identity_snapshot",
            "snapshot": str(self.snapshot),
            "records": len(self.records),
        }


def enrich_species_identity_metadata(prepared_registry: Path, provider: ChemicalIdentitySnapshotProvider) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    report: dict[str, Any] = {
        "schema_version": 1,
        "provider": "chemical_identity_snapshot",
        "updated_species": [],
        "conflicts": [],
        "summary": {"n_updated_species": 0, "n_conflicts": 0},
    }
    species_dir = prepared_registry / "species"
    if not species_dir.exists():
        return report

    for path in sorted(species_dir.glob("*.yaml")):
        species = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        species_id = species.get("id") or path.stem
        candidates = provider.find_species(species_id)
        if not candidates:
            continue
        candidate = candidates[0]
        changed = _apply_identity_candidate(species, candidate, report)
        if changed:
            path.write_text(
                yaml.safe_dump(species, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            report["updated_species"].append(species_id)

    report["summary"]["n_updated_species"] = len(report["updated_species"])
    report["summary"]["n_conflicts"] = len(report["conflicts"])
    return report


def _apply_identity_candidate(species: dict[str, Any], candidate: dict[str, Any], report: dict[str, Any]) -> bool:
    changed = False
    metadata = species.setdefault("metadata", {})

    aliases = _unique([*metadata.get("aliases", []), *candidate.get("aliases", [])])
    if aliases != metadata.get("aliases", []):
        metadata["aliases"] = aliases
        changed = True

    identifiers = metadata.setdefault("identifiers", {})
    for key, value in (candidate.get("identifiers") or {}).items():
        if value is not None and identifiers.get(key) in (None, ""):
            identifiers[key] = value
            changed = True

    ontology_tags = _unique([*metadata.get("ontology_tags", []), *candidate.get("ontology_tags", [])])
    if ontology_tags != metadata.get("ontology_tags", []):
        metadata["ontology_tags"] = ontology_tags
        changed = True

    source_records = metadata.setdefault("identity_source_records", [])
    for source_record in candidate.get("source_records", []):
        if isinstance(source_record, dict) and source_record not in source_records:
            source_records.append(deepcopy(source_record))
            changed = True

    formula = candidate.get("formula")
    if formula:
        existing_formula = species.get("formula")
        if existing_formula in (None, ""):
            species["formula"] = formula
            changed = True
        elif existing_formula != formula:
            report["conflicts"].append(
                {
                    "kind": "formula_conflict",
                    "species": species.get("id"),
                    "existing_formula": existing_formula,
                    "candidate_formula": formula,
                    "action": "manual_review",
                }
            )

        candidate_composition = _composition_from_formula(formula)
        existing_composition = species.get("composition")
        if candidate_composition and existing_composition and existing_composition != candidate_composition:
            report["conflicts"].append(
                {
                    "kind": "composition_conflict",
                    "species": species.get("id"),
                    "existing_composition": existing_composition,
                    "candidate_composition": candidate_composition,
                    "action": "manual_review",
                }
            )

    return changed


def _load_records(snapshot: Path) -> list[dict[str, Any]]:
    if not snapshot.exists():
        return []
    payload = yaml.safe_load(snapshot.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"chemical identity snapshot must be a YAML mapping: {snapshot}")
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValueError(f"chemical identity snapshot records must be a list: {snapshot}")
    return [record for record in records if isinstance(record, dict)]


def _matches(record: dict[str, Any], species_id: str) -> bool:
    aliases = [str(alias) for alias in record.get("aliases", [])]
    return species_id == record.get("species") or species_id in aliases


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
