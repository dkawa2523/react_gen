from __future__ import annotations

from typing import Any


PUBCHEM_CITATION = "PubChem PUG REST snapshot generated locally"


def extract_cid(payload: dict[str, Any]) -> int | None:
    cids = payload.get("IdentifierList", {}).get("CID", [])
    if not isinstance(cids, list) or not cids:
        return None
    try:
        return int(cids[0])
    except (TypeError, ValueError):
        return None


def extract_properties(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("PropertyTable", {}).get("Properties", [])
    if not isinstance(records, list) or not records:
        return {}
    first = records[0]
    return first if isinstance(first, dict) else {}


def extract_synonyms(payload: dict[str, Any], limit: int = 50) -> list[str]:
    records = payload.get("InformationList", {}).get("Information", [])
    if not isinstance(records, list) or not records:
        return []
    synonyms = records[0].get("Synonym", []) if isinstance(records[0], dict) else []
    if not isinstance(synonyms, list):
        return []

    aliases = []
    seen = set()
    for synonym in synonyms:
        if not isinstance(synonym, str):
            continue
        normalized = synonym.strip()
        if not normalized or normalized in seen:
            continue
        aliases.append(normalized)
        seen.add(normalized)
        if len(aliases) >= limit:
            break
    return aliases


def normalize_species_record(
    *,
    species_id: str,
    query: str,
    cid_payload: dict[str, Any],
    property_payload: dict[str, Any],
    synonym_payload: dict[str, Any] | None = None,
    raw_files: list[str] | None = None,
) -> dict[str, Any]:
    cid = extract_cid(cid_payload)
    properties = extract_properties(property_payload)
    if cid is None and properties.get("CID") is not None:
        try:
            cid = int(properties["CID"])
        except (TypeError, ValueError):
            cid = None

    identifiers: dict[str, Any] = {}
    if cid is not None:
        identifiers["pubchem_cid"] = cid
    if properties.get("InChIKey"):
        identifiers["inchikey"] = properties["InChIKey"]
    if properties.get("CanonicalSMILES"):
        identifiers["canonical_smiles"] = properties["CanonicalSMILES"]
    if properties.get("IsomericSMILES"):
        identifiers["isomeric_smiles"] = properties["IsomericSMILES"]

    return {
        "species": species_id,
        "query": query,
        "identifiers": identifiers,
        "formula": properties.get("MolecularFormula"),
        "molecular_weight": properties.get("MolecularWeight"),
        "aliases": extract_synonyms(synonym_payload or {}),
        "source_record": {
            "source_type": "public_database_api_snapshot",
            "database": "PubChem",
            "raw_files": list(raw_files or []),
            "citation": PUBCHEM_CITATION,
        },
    }
