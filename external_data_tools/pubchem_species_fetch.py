from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from external_data_tools.cache import safe_filename
from external_data_tools.pubchem_normalize import (
    extract_cid,
    extract_properties,
    normalize_species_record,
)
from external_data_tools.pubchem_urls import (
    build_cid_url,
    build_property_url,
    build_synonym_url,
)

JsonDownloader = Callable[[str, Path, list[str]], dict[str, Any]]


def fetch_species_record(
    entry: dict[str, str],
    *,
    run_root: Path,
    download_json: JsonDownloader,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    species_id = entry["id"]
    query = entry["query"]
    species_root = run_root / safe_filename(species_id)
    raw_files: list[str] = []
    cid_payload, error = _cid_payload(species_id, query, species_root, raw_files, download_json)
    if error is not None:
        return None, [error]
    cid = extract_cid(cid_payload)
    if cid is None:
        return None, [
            _unresolved(
                species_id,
                query,
                "cid_lookup",
                "no PubChem CID found",
                raw_files,
            )
        ]
    property_payload, error = _property_payload(
        species_id,
        query,
        cid,
        species_root,
        raw_files,
        download_json,
    )
    if error is not None:
        return None, [error]
    synonym_payload, warnings = _synonym_payload(
        species_id,
        query,
        cid,
        species_root,
        raw_files,
        download_json,
    )
    record = normalize_species_record(
        species_id=species_id,
        query=query,
        cid_payload=cid_payload,
        property_payload=property_payload,
        synonym_payload=synonym_payload,
        raw_files=raw_files,
    )
    return record, warnings


def _cid_payload(
    species_id: str,
    query: str,
    species_root: Path,
    raw_files: list[str],
    download_json: JsonDownloader,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        payload = download_json(
            build_cid_url(query),
            species_root / "cid_lookup.json",
            raw_files,
        )
        return payload, None
    except Exception as exc:
        return {}, _unresolved(species_id, query, "cid_lookup", str(exc), raw_files)


def _property_payload(
    species_id: str,
    query: str,
    cid: int,
    species_root: Path,
    raw_files: list[str],
    download_json: JsonDownloader,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        payload = download_json(
            build_property_url(cid),
            species_root / "properties.json",
            raw_files,
        )
    except Exception as exc:
        return {}, _unresolved(species_id, query, "properties", str(exc), raw_files)
    if not extract_properties(payload):
        return {}, _unresolved(
            species_id,
            query,
            "properties",
            "no PubChem property record found",
            raw_files,
        )
    return payload, None


def _synonym_payload(
    species_id: str,
    query: str,
    cid: int,
    species_root: Path,
    raw_files: list[str],
    download_json: JsonDownloader,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        payload = download_json(build_synonym_url(cid), species_root / "synonyms.json", raw_files)
        return payload, []
    except Exception as exc:
        return {}, [_unresolved(species_id, query, "synonyms", str(exc), raw_files)]


def _unresolved(
    species_id: str,
    query: str,
    stage: str,
    reason: str,
    raw_files: list[str],
) -> dict[str, Any]:
    return {
        "species": species_id,
        "query": query,
        "stage": stage,
        "reason": reason,
        "raw_files": list(raw_files),
    }
