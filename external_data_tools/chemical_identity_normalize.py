from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_identity_records(source_records: list[Any]) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for record in source_records:
        if not isinstance(record, dict):
            continue
        species = record.get("species")
        if not species:
            continue
        target = merged.setdefault(str(species), _empty_identity_record(str(species)))
        _merge_identity_record(target, record)
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
    normalized = (_chebi_record(record) for record in records if isinstance(record, dict))
    return [record for record in normalized if record is not None]


def _empty_identity_record(species: str) -> dict[str, Any]:
    return {
        "species": species,
        "query": None,
        "identifiers": {},
        "formula": None,
        "aliases": [],
        "ontology_tags": [],
        "source_records": [],
    }


def _merge_identity_record(target: dict[str, Any], record: dict[str, Any]) -> None:
    if record.get("query") and not target.get("query"):
        target["query"] = record["query"]
    if record.get("formula") and not target.get("formula"):
        target["formula"] = record["formula"]
    _merge_mapping(target["identifiers"], record.get("identifiers", {}))
    _merge_list(target["aliases"], record.get("aliases", []))
    _merge_list(target["ontology_tags"], record.get("ontology_tags", []))
    _append_source_records(target["source_records"], record)


def _append_source_records(target: list[dict[str, Any]], record: dict[str, Any]) -> None:
    source_record = record.get("source_record")
    if isinstance(source_record, dict):
        target.append(deepcopy(source_record))
    target.extend(
        deepcopy(item) for item in record.get("source_records", []) if isinstance(item, dict)
    )


def _chebi_record(record: dict[str, Any]) -> dict[str, Any] | None:
    species = _chebi_species(record)
    if not species:
        return None
    item = {
        "species": str(species),
        "query": record.get("query") or record.get("name") or species,
        "identifiers": _chebi_identifiers(record),
        "formula": record.get("formula"),
        "aliases": record.get("aliases", []),
        "ontology_tags": record.get("ontology_tags", []),
    }
    if record.get("raw_file"):
        item["source_record"] = {
            "database": "ChEBI",
            "raw_file": record.get("raw_file"),
        }
    return item


def _chebi_species(record: dict[str, Any]) -> Any:
    return record.get("species") or record.get("id") or record.get("formula")


def _chebi_identifiers(record: dict[str, Any]) -> dict[str, Any]:
    identifiers = {
        "chebi_id": record.get("chebi_id") or record.get("id"),
        "inchikey": record.get("inchikey"),
        "inchi": record.get("inchi"),
        "canonical_smiles": record.get("canonical_smiles") or record.get("smiles"),
    }
    return {key: value for key, value in identifiers.items() if value is not None}


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
