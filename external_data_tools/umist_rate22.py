"""Fetch and parse the native UMIST Rate22 reaction file."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from external_data_tools.cache import sha256_file
from external_data_tools.http_client import download_url
from external_data_tools.registry_admin_io import write_yaml

UMIST_RATE22_URL = "https://umistdatabase.uk/files/rate22_final.rates"
_MIN_FIELDS = 18


def read_umist_rate22(path: str | Path) -> list[dict[str, str]]:
    """Read the colon-delimited Rate22 release into the common network schema."""

    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        return [_canonical_row(fields, line_number) for line_number, fields in _rows(handle)]


def fetch_umist_rate22(output: str | Path) -> dict[str, Any]:
    """Download the official release and record a reproducible site-local checksum."""

    destination = Path(output)
    record = download_url(UMIST_RATE22_URL, destination)
    digest = sha256_file(destination)
    metadata = {
        "schema_version": 1,
        "database": "UMIST Rate22",
        "source_url": UMIST_RATE22_URL,
        "file": str(destination),
        "sha256": digest,
        "downloaded_at": record.get("downloaded_at"),
        "redistribution_status": "site-local",
    }
    write_yaml(destination.with_suffix(destination.suffix + ".metadata.yaml"), metadata)
    return metadata


def _rows(handle: Iterable[str]) -> Iterable[tuple[int, list[str]]]:
    reader = csv.reader(handle, delimiter=":", quotechar='"')
    for line_number, fields in enumerate(reader, start=1):
        if not fields or not any(field.strip() for field in fields):
            continue
        if len(fields) < _MIN_FIELDS:
            raise ValueError(
                f"UMIST Rate22 line {line_number} has {len(fields)} fields; "
                f"expected at least {_MIN_FIELDS}"
            )
        yield line_number, fields


def _canonical_row(fields: list[str], line_number: int) -> dict[str, str]:
    reaction_number = fields[0].strip()
    reaction_type = fields[1].strip()
    doi = fields[16].strip()
    citation = fields[17].strip()
    reference = "; ".join(value for value in (doi, citation) if value)
    return {
        "reactant1": fields[2].strip(),
        "reactant2": fields[3].strip(),
        "product1": fields[4].strip(),
        "product2": fields[5].strip(),
        "product3": fields[6].strip(),
        "product4": fields[7].strip(),
        "alpha": fields[9].strip(),
        "beta": fields[10].strip(),
        "gamma": fields[11].strip(),
        "temperature_min_K": fields[12].strip(),
        "temperature_max_K": fields[13].strip(),
        "source": f"UMIST Rate22:{reaction_number}:{reaction_type}",
        "reference": reference,
        "source_line": str(line_number),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the official UMIST Rate22 file.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = fetch_umist_rate22(args.output)
    print(f"UMIST Rate22 downloaded: sha256={result['sha256']} file={result['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
