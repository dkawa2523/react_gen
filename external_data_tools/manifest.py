from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml


def load_manifest(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"schema_version": 1, "records": []}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "records": []}
    records = payload.get("records", [])
    if not isinstance(records, list):
        records = []
    return {
        "schema_version": int(payload.get("schema_version", 1)),
        "records": records,
    }


def append_record(path: Path, record: dict) -> None:
    path = Path(path)
    manifest = load_manifest(path)
    manifest.setdefault("records", []).append(deepcopy(record))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

