"""Write what a converter produced as a snapshot `rgen ingest` can read.

Tables are written as two-column CSV assets next to the snapshot; the snapshot
references them by path. Nothing here decides whether the data is correct — that
is the reviewer's job, and `rgen ingest` puts anything ambiguous in a queue.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from reactgen import yamlio


def input_acquisition(input_path: Path) -> tuple[bytes, dict[str, Any]]:
    """Validate the local raw input and any adjacent acquisition declaration.

    A sidecar for another file is unrelated. A declaration for this file must
    identify these bytes before the converter writes a snapshot or raw copy.
    Its original paths belong to source_manifest, not the converted raw_path.
    """
    data = input_path.read_bytes()
    acquisition: dict[str, Any] = {
        "input_name": input_path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "raw_path": f"raw/{input_path.name}",
    }
    sidecar = input_path.with_name("acquisition.yaml")
    if sidecar.exists():
        manifest = _manifest(sidecar)
        if manifest["file"] == input_path.name:
            if manifest["sha256"].lower() != acquisition["sha256"]:
                raise ValueError(f"{sidecar}: acquisition hash does not match {input_path.name}")
            acquisition["source_manifest"] = manifest
    return data, acquisition


def _manifest(path: Path) -> dict[str, Any]:
    """Read a manifest shape; keep unknown declarations without interpreting them."""
    manifest = yamlio.load(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or any(not isinstance(key, str) for key in manifest):
        raise ValueError(f"{path}: acquisition manifest must be a mapping with text keys")
    filename = manifest.get("file")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise ValueError(f"{path}: acquisition manifest file must be a filename")
    checksum = manifest.get("sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError(f"{path}: acquisition manifest sha256 must be a full SHA-256")
    for name in ("provider", "collection", "release", "requested_url", "final_url", "retrieved_at"):
        value = manifest.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{path}: acquisition manifest {name} must be nonempty text")
    return manifest


def _source_records(
    source: dict[str, Any], records: list[dict], acquisition: dict[str, Any] | None
) -> tuple[dict[str, Any], list[dict]]:
    """Carry acquisition context into declarations consumed by evidence loaders."""
    saved_source, saved_records = deepcopy(source), deepcopy(records)
    if acquisition is None:
        return saved_source, saved_records
    manifest = acquisition.get("source_manifest", {})
    for name in ("provider", "collection", "release"):
        if name not in saved_source and manifest.get(name) is not None:
            saved_source[name] = manifest[name]
    if "acquisition" in saved_source and saved_source["acquisition"] != acquisition:
        raise ValueError("source.acquisition conflicts with conversion input")
    saved_source["acquisition"] = deepcopy(acquisition)
    for record in saved_records:
        if "source_declaration" not in record:
            continue  # The evidence loader includes snapshot_source itself.
        declaration = record["source_declaration"]
        if not isinstance(declaration, dict):
            declaration = {"record_declaration": declaration}
        prior = declaration.get("snapshot_source")
        if prior is not None and prior != saved_source:
            raise ValueError("source_declaration.snapshot_source conflicts with conversion source")
        record["source_declaration"] = declaration | {"snapshot_source": deepcopy(saved_source)}
    return saved_source, saved_records


def write(
    outdir: Path,
    kind: str,
    source: dict[str, Any],
    records: list[dict],
    *,
    input_path: Path | None = None,
) -> Path:
    acquisition = None
    if input_path is not None:
        data, acquisition = input_acquisition(input_path)
    saved_source, saved_records = _source_records(source, records, acquisition)
    body = yaml.safe_dump(
        {
            "snapshot_version": 1,
            "kind": kind,
            "source": saved_source,
            "records": saved_records,
            **({"acquisition": acquisition} if acquisition is not None else {}),
        },
        sort_keys=False,
        allow_unicode=True,
    )
    outdir.mkdir(parents=True, exist_ok=True)
    if input_path is not None:
        raw = outdir / "raw"
        raw.mkdir(exist_ok=True)
        destination = raw / input_path.name
        if input_path.resolve() != destination.resolve():
            destination.write_bytes(data)
    path = outdir / "snapshot.yaml"
    path.write_text(
        body,
        encoding="utf-8",
    )
    return path


def write_table(outdir: Path, name: str, rows: list[tuple[float, float]], header: str) -> str:
    """Write a two-column table and return its path relative to ``outdir``."""
    if any(
        isinstance(value, bool) or not isinstance(value, int | float)
        for row in rows
        for value in row
    ):
        raise ValueError("table values must be numbers")
    # repr preserves each parsed floating-point value; fixed six-decimal
    # scientific notation silently discarded source precision.
    body = "\n".join(f"{x!r},{y!r}" for x, y in rows)
    assets = outdir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    path = assets / f"{name}.csv"
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    return f"assets/{path.name}"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
