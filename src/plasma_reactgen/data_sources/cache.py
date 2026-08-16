from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import shutil

import yaml

from plasma_reactgen.domain.identifiers import to_file_key


def record_source_file(
    cache_root: str | Path,
    source_name: str,
    original_path: str | Path,
) -> dict[str, Any]:
    cache_root = Path(cache_root)
    original_path = Path(original_path)
    digest = _sha256(original_path)
    manifest_path = cache_root / "manifest.yaml"
    manifest = _load_manifest(manifest_path)

    cached_path = _cached_file_path(cache_root, source_name, original_path, digest)
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original_path, cached_path)

    record = {
        "source_type": "local_file_cache",
        "source_name": source_name,
        "original_path": str(original_path),
        "cached_path": str(cached_path.relative_to(cache_root)),
        "sha256": digest,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    if any(item.get("sha256") == digest for item in manifest["source_files"]):
        record["notes"] = ["A source file with the same sha256 was already recorded."]

    manifest["source_files"].append(record)
    _write_manifest(manifest_path, manifest)
    return record


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "source_files": []}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    source_files = payload.get("source_files", [])
    if not isinstance(source_files, list):
        source_files = []
    return {
        "schema_version": int(payload.get("schema_version", 1)),
        "source_files": source_files,
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _cached_file_path(cache_root: Path, source_name: str, original_path: Path, digest: str) -> Path:
    safe_source = to_file_key(source_name)
    safe_stem = to_file_key(original_path.stem)
    suffix = original_path.suffix
    return cache_root / safe_source / f"{safe_stem}_{digest[:12]}{suffix}"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
