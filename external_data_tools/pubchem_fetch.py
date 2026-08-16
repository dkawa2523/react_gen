from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .http_client import download_url
from .pubchem_species_fetch import fetch_species_record
from .pubchem_urls import (
    build_cid_url as build_cid_url,
)
from .pubchem_urls import (
    build_property_url as build_property_url,
)
from .pubchem_urls import (
    build_synonym_url as build_synonym_url,
)


def fetch_pubchem_snapshot(
    species_list_path: Path,
    *,
    output_root: Path,
    snapshot_path: Path,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    species_entries = _load_species_entries(species_list_path)
    snapshot_path = Path(snapshot_path)
    output_root = Path(output_root)

    if not dry_run and snapshot_path.exists() and not overwrite:
        raise FileExistsError(f"snapshot already exists: {snapshot_path}")

    if dry_run:
        return _dry_run_plan(species_entries)

    run_root = output_root / f"run_{_timestamp_for_path()}"
    records = []
    unresolved = []

    for entry in species_entries:
        record, errors = fetch_species_record(
            entry,
            run_root=run_root,
            download_json=_download_json,
        )
        unresolved.extend(errors)
        if record is not None:
            records.append(record)

    snapshot = {
        "schema_version": 1,
        "source": {
            "source_type": "public_database_api_snapshot",
            "database": "PubChem",
            "access_mode": "pug_rest",
            "generated_at": _utc_now(),
        },
        "records": records,
        "unresolved": unresolved,
    }
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        yaml.safe_dump(snapshot, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch small PubChem identity snapshots for user-provided species."
    )
    parser.add_argument("species_list", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("external_data/raw/pubchem"))
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("external_data/snapshots/pubchem_species.yaml"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = fetch_pubchem_snapshot(
            args.species_list,
            output_root=args.output_root,
            snapshot_path=args.snapshot,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"pubchem fetch: {exc}")
        return 1

    if args.dry_run:
        summary = result["summary"]
        print(
            "pubchem fetch dry-run: "
            f"total_species={summary['total_species']} "
            f"planned_species={summary['planned_species']}"
        )
        return 0

    print(
        "pubchem fetch: "
        f"records={len(result['records'])} "
        f"unresolved={len(result['unresolved'])} "
        f"snapshot={args.snapshot}"
    )
    return 0


def _download_json(url: str, output_path: Path, raw_files: list[str]) -> dict[str, Any]:
    record = download_url(url, output_path)
    raw_files.append(record["output_path"])
    payload = json.loads(Path(record["output_path"]).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"PubChem response was not a JSON object: {url}")
    return payload


def _dry_run_plan(species_entries: list[dict[str, str]]) -> dict[str, Any]:
    planned = [
        {
            "species": entry["id"],
            "query": entry["query"],
            "urls": {
                "cid_lookup": build_cid_url(entry["query"]),
                "properties": "requires CID lookup",
                "synonyms": "requires CID lookup",
            },
        }
        for entry in species_entries
    ]
    return {
        "schema_version": 1,
        "dry_run": True,
        "summary": {
            "total_species": len(species_entries),
            "planned_species": len(species_entries),
            "records": 0,
            "unresolved": 0,
        },
        "planned": planned,
    }


def _load_species_entries(path: Path) -> list[dict[str, str]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("species list must be a YAML mapping")
    entries = payload.get("species", [])
    if not isinstance(entries, list):
        raise ValueError("species list must contain a species list")

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("species entries must be mappings")
        species_id = entry.get("id")
        query = entry.get("query")
        if not species_id or not query:
            raise ValueError("species entries require id and query")
        normalized.append({"id": str(species_id), "query": str(query)})
    return normalized


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp_for_path() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


if __name__ == "__main__":
    raise SystemExit(main())
