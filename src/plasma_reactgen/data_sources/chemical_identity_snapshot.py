from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.data_sources.chemical_identity_merge import merge_identity_candidate


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


def enrich_species_identity_metadata(
    prepared_registry: Path, provider: ChemicalIdentitySnapshotProvider
) -> dict[str, Any]:
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
        changed, conflicts = merge_identity_candidate(species, candidate)
        report["conflicts"].extend(conflicts)
        if changed:
            path.write_text(
                yaml.safe_dump(species, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            report["updated_species"].append(species_id)

    report["summary"]["n_updated_species"] = len(report["updated_species"])
    report["summary"]["n_conflicts"] = len(report["conflicts"])
    return report


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
