from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_identity_records(source_records: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for record in source_records:
        if not isinstance(record, dict):
            continue
        species = record.get("species")
        if not species:
            continue
        target = merged.setdefault(
            str(species),
            {
                "species": str(species),
                "query": record.get("query"),
                "identifiers": {},
                "formula": record.get("formula"),
                "aliases": [],
                "ontology_tags": [],
                "source_records": [],
            },
        )
        if record.get("query") and not target.get("query"):
            target["query"] = record["query"]
        if record.get("formula") and not target.get("formula"):
            target["formula"] = record["formula"]
        _merge_mapping(target["identifiers"], record.get("identifiers", {}))
        _merge_list(target["aliases"], record.get("aliases", []))
        _merge_list(target["ontology_tags"], record.get("ontology_tags", []))
        source_record = record.get("source_record")
        if isinstance(source_record, dict):
            target["source_records"].append(deepcopy(source_record))
        for item in record.get("source_records", []):
            if isinstance(item, dict):
                target["source_records"].append(deepcopy(item))
    return {
        "schema_version": 1,
        "source": {
            "source_type": "local_snapshot",
            "database": "chemical_identity_merged",
        },
        "records": list(merged.values()),
    }


def chebi_records_from_local_snapshot(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records", [])
    if not isinstance(records, list):
        return []
    normalized = []
    for record in records:
        if not isinstance(record, dict):
            continue
        species = record.get("species") or record.get("id") or record.get("formula")
        if not species:
            continue
        item = {
            "species": str(species),
            "query": record.get("query") or record.get("name") or species,
            "identifiers": {
                key: value
                for key, value in {
                    "chebi_id": record.get("chebi_id") or record.get("id"),
                    "inchikey": record.get("inchikey"),
                    "inchi": record.get("inchi"),
                    "canonical_smiles": record.get("canonical_smiles") or record.get("smiles"),
                }.items()
                if value is not None
            },
            "formula": record.get("formula"),
            "aliases": record.get("aliases", []),
            "ontology_tags": record.get("ontology_tags", []),
        }
        if record.get("raw_file"):
            item["source_record"] = {
                "database": "ChEBI",
                "raw_file": record.get("raw_file"),
            }
        normalized.append(item)
    return normalized


def _merge_mapping(target: dict[str, Any], incoming: Any) -> None:
    if not isinstance(incoming, dict):
        return
    for key, value in incoming.items():
        if value is not None and target.get(key) in (None, ""):
            target[key] = value


def _merge_list(target: list[str], incoming: Any) -> None:
    if not isinstance(incoming, list):
        return
    seen = set(target)
    for item in incoming:
        value = str(item)
        if value and value not in seen:
            target.append(value)
            seen.add(value)
