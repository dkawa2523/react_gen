"""Fetch a licensed QDB chemistry as a site-local raw artifact."""

from __future__ import annotations

import argparse
import os
import urllib.parse
from pathlib import Path
from typing import Any

from external_data_tools.cache import sha256_file
from external_data_tools.http_client import download_url
from external_data_tools.registry_admin_io import write_yaml

QDB_API_URL = "https://www.quantemoldb.com/reactions/api/"


def fetch_qdb_chemistry(
    chemistry_id: int,
    output: str | Path,
    *,
    api_key: str,
    all_datasets: bool = False,
    no_xsecs: bool = True,
) -> dict[str, Any]:
    """Cache one API response without logging or persisting the API key."""

    key = api_key.strip()
    if not key:
        raise ValueError("A non-empty QDB API key is required")
    if chemistry_id <= 0:
        raise ValueError("chemistry_id must be a positive integer")

    parameters = {
        "key": key,
        "chemistry_id": str(chemistry_id),
        "all_datasets": str(all_datasets).lower(),
        "no_xsecs": str(no_xsecs).lower(),
    }
    request_url = f"{QDB_API_URL}?{urllib.parse.urlencode(parameters)}"
    destination = Path(output)
    record = download_url(
        request_url,
        destination,
        sensitive_query_keys={"key"},
    )
    metadata = {
        "schema_version": 1,
        "database": "Quantemol-DB",
        "source_url": QDB_API_URL,
        "chemistry_id": chemistry_id,
        "request": {
            "all_datasets": all_datasets,
            "no_xsecs": no_xsecs,
            "api_key_recorded": False,
        },
        "file": str(destination),
        "sha256": sha256_file(destination),
        "downloaded_at": record.get("downloaded_at"),
        "response_format": "Q-VT-compatible chemistry response",
        "redistribution_status": "site-local_license_review_required",
        "promotion_status": "raw_review_required",
    }
    write_yaml(destination.with_suffix(destination.suffix + ".metadata.yaml"), metadata)
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch one licensed QDB chemistry response.")
    parser.add_argument("--chemistry-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all-datasets", action="store_true")
    parser.add_argument("--with-cross-sections", action="store_true")
    args = parser.parse_args(argv)
    api_key = os.environ.get("QDB_API_KEY", "")
    if not api_key:
        parser.error("Set QDB_API_KEY in the environment; command-line keys are not accepted.")
    result = fetch_qdb_chemistry(
        args.chemistry_id,
        args.output,
        api_key=api_key,
        all_datasets=args.all_datasets,
        no_xsecs=not args.with_cross_sections,
    )
    print(
        "QDB chemistry cached site-locally: "
        f"id={result['chemistry_id']} sha256={result['sha256']} file={result['file']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
