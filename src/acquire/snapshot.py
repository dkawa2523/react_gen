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
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from reactgen import yamlio

RawInput = tuple[bytes, dict[str, Any]]


def raw_input(name: str, data: bytes) -> RawInput:
    """Identify the exact input that a converter reads and retains."""
    checksum = hashlib.sha256(data).hexdigest()
    return data, {
        "input_name": name,
        "sha256": checksum,
        "raw_path": f"raw/{checksum}/{name}",
    }


def input_acquisition(input_path: Path) -> RawInput:
    """Validate the local raw input and any adjacent acquisition declaration.

    A sidecar for another file is unrelated. A declaration for this file must
    identify these bytes before the converter writes a snapshot or raw copy.
    Its original paths belong to source_manifest, not the converted raw_path.
    """
    data, acquisition = raw_input(input_path.name, input_path.read_bytes())
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
    input_data: RawInput | None = None,
    raw_pages: tuple[RawInput, ...] = (),
) -> Path:
    """Publish a snapshot after its content-identified dependencies exist."""
    if input_path is not None:
        if input_data is not None:
            raise ValueError("provide either input_path or an already captured input")
        input_data = input_acquisition(input_path)
    acquisition = input_data[1] if input_data is not None else None
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
    inputs = raw_pages if input_data is None else (input_data, *raw_pages)
    for data, declaration in inputs:
        _publish_asset(outdir / declaration["raw_path"], data)
    path = outdir / "snapshot.yaml"
    _replace_bytes(path, body.encode("utf-8"))
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
    data = f"{header}\n{body}\n".encode()
    checksum = hashlib.sha256(data).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    relative = f"assets/{checksum}/{safe_name}.csv"
    _publish_asset(outdir / relative, data)
    return relative


def _publish_asset(path: Path, data: bytes) -> None:
    if not path.is_file() or path.read_bytes() != data:
        _replace_bytes(path, data)


def _replace_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(data)
        staged.replace(path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
