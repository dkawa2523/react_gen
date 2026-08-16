from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.models import CollisionPair


class LxcatOfflineCrossSectionProvider:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.records = _load_index(self.root / "index.yaml")

    def find_cross_sections(
        self, pair: CollisionPair | str | dict[str, Any]
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for record in self.records:
            if not _matches(record, pair):
                continue
            candidate = deepcopy(record)
            path = candidate.get("path") or candidate.get("file")
            if path is not None:
                candidate["path"] = str(path)
            source_id = candidate.get("reaction_id") or candidate.get("channel_id") or path
            candidate.setdefault(
                "status",
                "local_file_registered"
                if _asset_exists(self.root, path)
                else "path_registered_but_missing",
            )
            candidate.setdefault(
                "source_record",
                {
                    "source_type": "public_database_snapshot",
                    "database": "LXCat",
                    "source_id": f"lxcat_offline:{source_id}",
                },
            )
            candidates.append(candidate)
        return candidates


def _load_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        data = data.get("records", data.get("items", []))
    if not isinstance(data, list):
        raise ValueError(f"LXCat offline index must contain a list of records: {path}")
    return [deepcopy(record) for record in data if isinstance(record, dict)]


def _matches(record: dict[str, Any], query: CollisionPair | str | dict[str, Any]) -> bool:
    if isinstance(query, str):
        return query in {record.get("reaction_id"), record.get("channel_id")}
    if isinstance(query, CollisionPair):
        pair = record.get("pair")
        if isinstance(pair, dict):
            return _pair_payload(query) == {
                "family": str(pair.get("family", query.family)),
                "projectile": str(pair.get("projectile", "")),
                "target": str(pair.get("target", "")),
            }
        return record.get("target") == query.target
    return record.get("pair") == query


def _asset_exists(root: Path, path: Any) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.exists()
    return (root / candidate).exists()


def _pair_payload(pair: CollisionPair) -> dict[str, str]:
    return {
        "family": pair.family,
        "projectile": pair.projectile,
        "target": pair.target,
    }
