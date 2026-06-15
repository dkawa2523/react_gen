from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

import yaml

from .cache import safe_filename, sha256_file
from .chemical_identity_normalize import chebi_records_from_local_snapshot, normalize_identity_records


PROVIDERS = {"chebi", "chemspider", "opsin", "nci_cactus"}


def fetch_chemical_identity(
    species_list_path: Path,
    *,
    output_root: Path,
    snapshot_path: Path,
    provider: str = "chebi",
    dry_run: bool = False,
    local_snapshot: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported identity provider: {provider}")
    species_entries = _load_species_entries(species_list_path)
    output_root = Path(output_root)
    snapshot_path = Path(snapshot_path)

    if not dry_run and snapshot_path.exists() and not overwrite:
        raise FileExistsError(f"snapshot already exists: {snapshot_path}")

    if dry_run:
        return {
            "schema_version": 1,
            "dry_run": True,
            "provider": provider,
            "summary": {
                "total_species": len(species_entries),
                "planned": len(species_entries),
                "records": 0,
                "unresolved": 0,
            },
            "planned": [
                {"species": entry["id"], "query": entry["query"], "provider": provider}
                for entry in species_entries
            ],
        }

    records: list[dict[str, Any]] = []
    unresolved = []
    if provider == "chebi":
        if local_snapshot is None:
            unresolved.extend(
                {
                    "species": entry["id"],
                    "query": entry["query"],
                    "provider": provider,
                    "reason": "local_snapshot_required",
                }
                for entry in species_entries
            )
        else:
            source_payload = _read_yaml(local_snapshot)
            raw_record = _cache_local_snapshot(local_snapshot, output_root, provider)
            by_query = _match_records(chebi_records_from_local_snapshot(source_payload), species_entries)
            for entry in species_entries:
                matched = by_query.get(entry["id"])
                if matched is None:
                    unresolved.append(
                        {
                            "species": entry["id"],
                            "query": entry["query"],
                            "provider": provider,
                            "reason": "no_local_snapshot_match",
                        }
                    )
                    continue
                matched.setdefault("source_records", []).append(raw_record)
                records.append(matched)
    else:
        availability = _provider_availability(provider)
        unresolved.extend(
            {
                "species": entry["id"],
                "query": entry["query"],
                "provider": provider,
                "reason": availability["reason"],
            }
            for entry in species_entries
        )

    snapshot = normalize_identity_records(records)
    snapshot["source"]["generated_at"] = _utc_now()
    snapshot["source"]["provider"] = provider
    snapshot["unresolved"] = unresolved
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        yaml.safe_dump(snapshot, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    source_files = [item for record in records for item in record.get("source_records", []) if isinstance(item, dict)]
    _write_source_manifest(output_root / "manifest.yaml", provider, snapshot_path, records, unresolved, source_files)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build local chemical identity snapshots from optional external identity providers."
    )
    parser.add_argument("species_list", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("external_data/raw/chemical_identity"))
    parser.add_argument("--snapshot", type=Path, default=Path("external_data/snapshots/chemical_identity.yaml"))
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="chebi")
    parser.add_argument("--local-snapshot", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = fetch_chemical_identity(
            args.species_list,
            output_root=args.output_root,
            snapshot_path=args.snapshot,
            provider=args.provider,
            dry_run=args.dry_run,
            local_snapshot=args.local_snapshot,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"chemical identity fetch: {exc}")
        return 1

    if args.dry_run:
        print(
            "chemical identity fetch dry-run: "
            f"provider={args.provider} planned={result['summary']['planned']}"
        )
        return 0
    print(
        "chemical identity fetch: "
        f"provider={args.provider} records={len(result.get('records', []))} "
        f"unresolved={len(result.get('unresolved', []))} snapshot={args.snapshot}"
    )
    return 0


def _provider_availability(provider: str) -> dict[str, Any]:
    if provider == "chemspider":
        if os.environ.get("CHEMSPIDER_API_KEY"):
            return {"available": False, "reason": "chemspider_online_fetch_not_implemented"}
        return {"available": False, "reason": "chemspider_api_key_not_configured"}
    if provider == "opsin":
        if os.environ.get("REACTGEN_ENABLE_OPSIN_ONLINE") == "1":
            return {"available": False, "reason": "opsin_online_fetch_not_implemented"}
        return {"available": False, "reason": "opsin_online_disabled"}
    if provider == "nci_cactus":
        if os.environ.get("REACTGEN_ENABLE_NCI_CACTUS_ONLINE") == "1":
            return {"available": False, "reason": "nci_cactus_online_fetch_not_implemented"}
        return {"available": False, "reason": "nci_cactus_online_disabled"}
    return {"available": False, "reason": "provider_unavailable"}


def _load_species_entries(path: Path) -> list[dict[str, str]]:
    payload = _read_yaml(path)
    entries = payload.get("species", [])
    if not isinstance(entries, list):
        raise ValueError("species list must contain a species list")
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("query"):
            raise ValueError("species entries require id and query")
        normalized.append({"id": str(entry["id"]), "query": str(entry["query"])})
    return normalized


def _match_records(records: list[dict[str, Any]], species_entries: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    matched = {}
    for entry in species_entries:
        query = entry["query"].lower()
        species_id = entry["id"]
        for record in records:
            aliases = [str(alias).lower() for alias in record.get("aliases", [])]
            if (
                str(record.get("species", "")).lower() == species_id.lower()
                or str(record.get("query", "")).lower() == query
                or query in aliases
            ):
                copy = dict(record)
                copy["species"] = species_id
                copy["query"] = entry["query"]
                matched[species_id] = copy
                break
    return matched


def _cache_local_snapshot(local_snapshot: Path, output_root: Path, provider: str) -> dict[str, Any]:
    output = output_root / provider / f"{safe_filename(local_snapshot.stem)}{local_snapshot.suffix}"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(Path(local_snapshot).read_bytes())
    return {
        "database": "ChEBI" if provider == "chebi" else provider,
        "raw_file": str(output),
        "sha256": sha256_file(output),
    }


def _write_source_manifest(
    path: Path,
    provider: str,
    snapshot_path: Path,
    records: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    source_files: list[dict[str, Any]],
) -> None:
    payload = {
        "schema_version": 1,
        "provider": provider,
        "snapshot": str(snapshot_path),
        "generated_at": _utc_now(),
        "records": len(records),
        "unresolved": len(unresolved),
        "source_files": source_files,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML input must be a mapping: {path}")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
