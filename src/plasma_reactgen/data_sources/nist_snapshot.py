from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.data_sources.base import PropertyProvider


SUPPORTED_PROPERTIES = {
    "mass_amu",
    "ionization_energy_eV",
    "electron_affinity_eV",
    "enthalpy_formation_eV",
    "dipole_moment_D",
    "polarizability_A3",
    "vertical_ionization_energy_eV",
}

SUPPORTED_UNITS = {"eV", "amu", "D", "A3"}


class NistSnapshotPropertyProvider(PropertyProvider):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.records = _load_records(self.root)
        self.unresolved: list[dict[str, Any]] = []

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.unresolved = []
        requested = set(names) if names is not None else SUPPORTED_PROPERTIES
        candidates: list[dict[str, Any]] = []

        for record in self.records:
            property_name = record.get("property")
            if not _matches_species(record, species_id):
                continue
            if property_name not in requested or property_name not in SUPPORTED_PROPERTIES:
                continue

            unit = record.get("unit")
            if unit not in SUPPORTED_UNITS:
                self.unresolved.append(
                    {
                        "species": species_id,
                        "property": property_name,
                        "unit": unit,
                        "reason": "unsupported_unit",
                    }
                )
                continue

            candidates.append(_candidate_payload(record))

        return candidates

    def status(self) -> dict[str, Any]:
        return {
            "available": self.root.exists(),
            "source": "nist_snapshot",
            "root": str(self.root),
            "unresolved": list(self.unresolved),
        }


def _load_records(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if isinstance(data, dict):
            data = data.get("records", data.get("items", []))
        if not isinstance(data, list):
            raise ValueError(f"NIST snapshot file must contain a list of records: {path}")
        records.extend(deepcopy(record) for record in data if isinstance(record, dict))
    return records


def _matches_species(record: dict[str, Any], species_id: str) -> bool:
    aliases = [str(alias) for alias in record.get("aliases", [])]
    return species_id == record.get("species") or species_id in aliases


def _candidate_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "species": record.get("species"),
        "property": record.get("property"),
        "value": record.get("value"),
        "unit": record.get("unit"),
        "status": record.get("status", "literature_supported"),
        "evidence_type": record.get("evidence_type"),
        "source_record": deepcopy(record.get("source_record")),
    }
    if record.get("source") is not None:
        payload["source"] = record.get("source")
    return payload
