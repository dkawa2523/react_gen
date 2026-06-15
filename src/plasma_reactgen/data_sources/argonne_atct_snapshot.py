from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

from plasma_reactgen.data_sources.base import PropertyProvider


SUPPORTED_PROPERTIES = {
    "enthalpy_formation_eV",
    "ionization_energy_eV",
    "electron_affinity_eV",
    "bond_dissociation_energy_eV",
    "atomization_energy_eV",
}


class ArgonneAtctSnapshotPropertyProvider(PropertyProvider):
    """Read reviewed local Argonne/ATcT-style thermochemistry snapshots."""

    def __init__(self, files: str | Path | Iterable[str | Path]):
        if isinstance(files, (str, Path)):
            self.files = [Path(files)]
        else:
            self.files = [Path(path) for path in files]
        self.records = _load_records(self.files)

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        requested = set(names) if names is not None else SUPPORTED_PROPERTIES
        candidates = []
        for record in self.records:
            property_name = record.get("property")
            if property_name not in requested or property_name not in SUPPORTED_PROPERTIES:
                continue
            if not _matches_species(record, species_id):
                continue
            if record.get("unit") != "eV" or record.get("value") is None:
                continue
            candidates.append(_candidate(record))
        return candidates

    def status(self) -> dict[str, Any]:
        return {
            "available": any(path.exists() for path in self.files),
            "source": "argonne_atct_snapshot",
            "files": [str(path) for path in self.files],
            "records": len(self.records),
        }


def _load_records(files: list[Path]) -> list[dict[str, Any]]:
    records = []
    for path in files:
        if not path.exists():
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Argonne/ATcT snapshot must be a YAML mapping: {path}")
        for record in payload.get("records", []):
            if isinstance(record, dict):
                records.append(deepcopy(record))
    return records


def _matches_species(record: dict[str, Any], species_id: str) -> bool:
    aliases = [str(alias) for alias in record.get("aliases", [])]
    return species_id == record.get("species") or species_id in aliases


def _candidate(record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "species": record.get("species"),
        "property": record.get("property"),
        "value": record.get("value"),
        "unit": record.get("unit"),
        "status": record.get("status", "literature_supported"),
        "temperature_K": record.get("temperature_K"),
        "uncertainty_eV": record.get("uncertainty_eV"),
        "source_record": deepcopy(record.get("source_record")),
    }
    if record.get("source") is not None:
        payload["source"] = record.get("source")
    return payload
