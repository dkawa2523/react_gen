from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .cache import safe_filename, sha256_file
from .chemical_identity_artifacts import read_yaml_mapping
from .chemical_identity_normalize import chebi_records_from_local_snapshot

PROVIDERS = {"chebi", "chemspider", "opsin", "nci_cactus"}


def collect_identity_records(
    provider: str,
    species_entries: list[dict[str, str]],
    output_root: Path,
    local_snapshot: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if provider == "chebi":
        return _collect_chebi_records(species_entries, output_root, local_snapshot)
    reason = _provider_unavailable_reason(provider)
    return [], _unresolved_entries(species_entries, provider, reason)


def _collect_chebi_records(
    species_entries: list[dict[str, str]],
    output_root: Path,
    local_snapshot: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if local_snapshot is None:
        return [], _unresolved_entries(
            species_entries,
            "chebi",
            "local_snapshot_required",
        )

    source_payload = read_yaml_mapping(local_snapshot)
    source_record = _cache_local_snapshot(local_snapshot, output_root, "chebi")
    matched_records = _match_records(
        chebi_records_from_local_snapshot(source_payload),
        species_entries,
    )
    records = []
    unresolved = []
    for entry in species_entries:
        matched = matched_records.get(entry["id"])
        if matched is None:
            unresolved.extend(_unresolved_entries([entry], "chebi", "no_local_snapshot_match"))
            continue
        matched.setdefault("source_records", []).append(source_record)
        records.append(matched)
    return records, unresolved


def _provider_unavailable_reason(provider: str) -> str:
    if provider == "chemspider":
        return (
            "chemspider_online_fetch_not_implemented"
            if os.environ.get("CHEMSPIDER_API_KEY")
            else "chemspider_api_key_not_configured"
        )
    if provider == "opsin":
        return (
            "opsin_online_fetch_not_implemented"
            if os.environ.get("REACTGEN_ENABLE_OPSIN_ONLINE") == "1"
            else "opsin_online_disabled"
        )
    if provider == "nci_cactus":
        return (
            "nci_cactus_online_fetch_not_implemented"
            if os.environ.get("REACTGEN_ENABLE_NCI_CACTUS_ONLINE") == "1"
            else "nci_cactus_online_disabled"
        )
    return "provider_unavailable"


def _unresolved_entries(
    species_entries: list[dict[str, str]],
    provider: str,
    reason: str,
) -> list[dict[str, Any]]:
    return [
        {
            "species": entry["id"],
            "query": entry["query"],
            "provider": provider,
            "reason": reason,
        }
        for entry in species_entries
    ]


def _match_records(
    records: list[dict[str, Any]],
    species_entries: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    matched = {}
    for entry in species_entries:
        match = _matching_record(records, entry)
        if match is not None:
            match["species"] = entry["id"]
            match["query"] = entry["query"]
            matched[entry["id"]] = match
    return matched


def _matching_record(
    records: list[dict[str, Any]],
    entry: dict[str, str],
) -> dict[str, Any] | None:
    query = entry["query"].lower()
    species_id = entry["id"].lower()
    for record in records:
        aliases = [str(alias).lower() for alias in record.get("aliases", [])]
        if (
            str(record.get("species", "")).lower() == species_id
            or str(record.get("query", "")).lower() == query
            or query in aliases
        ):
            return dict(record)
    return None


def _cache_local_snapshot(
    local_snapshot: Path,
    output_root: Path,
    provider: str,
) -> dict[str, Any]:
    output = output_root / provider / f"{safe_filename(local_snapshot.stem)}{local_snapshot.suffix}"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(Path(local_snapshot).read_bytes())
    return {
        "database": "ChEBI" if provider == "chebi" else provider,
        "raw_file": str(output),
        "sha256": sha256_file(output),
    }
