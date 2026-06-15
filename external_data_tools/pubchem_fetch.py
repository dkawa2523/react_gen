from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .cache import safe_filename
from .http_client import download_url
from .pubchem_normalize import extract_cid, extract_properties, normalize_species_record


PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def build_cid_url(query: str) -> str:
    return f"{PUBCHEM_BASE_URL}/compound/name/{quote(query, safe='')}/cids/JSON"


def build_property_url(cid: int) -> str:
    properties = ",".join(
        [
            "MolecularFormula",
            "MolecularWeight",
            "CanonicalSMILES",
            "IsomericSMILES",
            "InChIKey",
        ]
    )
    return f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/property/{properties}/JSON"


def build_synonym_url(cid: int) -> str:
    return f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/synonyms/JSON"


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

    run_root = output_root / f"run_{_timestamp_for_path()}"
    records = []
    unresolved = []

    for entry in species_entries:
        species_id = entry["id"]
        query = entry["query"]
        species_root = run_root / safe_filename(species_id)
        raw_files: list[str] = []

        try:
            cid_payload = _download_json(
                build_cid_url(query),
                species_root / "cid_lookup.json",
                raw_files,
            )
            cid = extract_cid(cid_payload)
            if cid is None:
                unresolved.append(
                    _unresolved(species_id, query, "cid_lookup", "no PubChem CID found", raw_files)
                )
                continue
        except Exception as exc:
            unresolved.append(_unresolved(species_id, query, "cid_lookup", str(exc), raw_files))
            continue

        try:
            property_payload = _download_json(
                build_property_url(cid),
                species_root / "properties.json",
                raw_files,
            )
            if not extract_properties(property_payload):
                unresolved.append(
                    _unresolved(
                        species_id,
                        query,
                        "properties",
                        "no PubChem property record found",
                        raw_files,
                    )
                )
                continue
        except Exception as exc:
            unresolved.append(_unresolved(species_id, query, "properties", str(exc), raw_files))
            continue

        synonym_payload: dict[str, Any] = {}
        try:
            synonym_payload = _download_json(
                build_synonym_url(cid),
                species_root / "synonyms.json",
                raw_files,
            )
        except Exception as exc:
            unresolved.append(_unresolved(species_id, query, "synonyms", str(exc), raw_files))

        records.append(
            normalize_species_record(
                species_id=species_id,
                query=query,
                cid_payload=cid_payload,
                property_payload=property_payload,
                synonym_payload=synonym_payload,
                raw_files=raw_files,
            )
        )

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_for_path() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


if __name__ == "__main__":
    raise SystemExit(main())
