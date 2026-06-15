from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

from plasma_reactgen.data_sources.base import ReactionProvider
from plasma_reactgen.domain.models import CollisionPair


class IonReactionTableProvider(ReactionProvider):
    """Read reviewed local ion-neutral reaction snapshots from simple YAML files."""

    def __init__(self, files: str | Path | Iterable[str | Path]):
        if isinstance(files, (str, Path)):
            self.files = [Path(files)]
        else:
            self.files = [Path(path) for path in files]
        self._records = _load_records(self.files)

    def find_reactions(
        self,
        reactants: list[str],
        family: str | None = None,
    ) -> list[dict[str, Any]]:
        if family not in {None, "ion_neutral"} or len(reactants) != 2:
            return []
        return self.find_channels(CollisionPair("ion_neutral", reactants[0], reactants[1]))

    def find_channels(self, pair: CollisionPair | dict[str, Any]) -> list[dict[str, Any]]:
        pair_payload = _pair_payload(pair)
        if pair_payload.get("family") != "ion_neutral":
            return []

        matches: list[dict[str, Any]] = []
        for record in self._records:
            if record.get("pair") != pair_payload:
                continue
            matches.append(deepcopy(record))
        return matches


def _load_records(files: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in files:
        if not path.exists():
            continue
        payload = _load_yaml(path)
        source = payload.get("source", {})
        for reaction in payload.get("reactions", []):
            if not isinstance(reaction, dict):
                continue
            channel = _channel_from_record(reaction, source)
            if channel is not None:
                records.append(channel)
    return records


def _channel_from_record(record: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
    family = str(record.get("family", "ion_neutral"))
    if family != "ion_neutral":
        return None
    projectile = record.get("projectile")
    target = record.get("target")
    if not projectile or not target:
        return None

    channel: dict[str, Any] = {
        "id": record.get("id"),
        "pair": {
            "family": "ion_neutral",
            "projectile": str(projectile),
            "target": str(target),
        },
        "type": record.get("type"),
        "products": deepcopy(record.get("products", [])),
        "status": _candidate_status(record.get("status")),
    }
    for key in (
        "dnt_class",
        "deltaE_products_minus_reactants_eV",
        "threshold_eV",
        "citation",
        "evidence_type",
        "confidence",
        "inference",
    ):
        if key in record:
            channel[key] = deepcopy(record[key])

    data = deepcopy(record.get("data", {}))
    if data:
        channel["data"] = data

    channel["source_record"] = _source_record(record, source)
    return channel


def _source_record(record: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    if isinstance(record.get("source_record"), dict):
        return deepcopy(record["source_record"])

    source_record: dict[str, Any] = {}
    for key in ("source_type", "database", "version"):
        if source.get(key) is not None:
            source_record[key] = deepcopy(source[key])
    source_record.setdefault("source_type", "local_snapshot")
    source_record["source_id"] = record.get("source_id") or record.get("id")
    if record.get("citation") is not None:
        source_record["citation"] = deepcopy(record["citation"])
    if record.get("evidence_type") is not None:
        source_record["evidence_type"] = deepcopy(record["evidence_type"])
    return source_record


def _candidate_status(status: Any) -> str:
    if status in {"curated", "literature_supported"}:
        return str(status)
    return "imported"


def _pair_payload(pair: CollisionPair | dict[str, Any]) -> dict[str, str]:
    if isinstance(pair, CollisionPair):
        return {
            "family": pair.family,
            "projectile": pair.projectile,
            "target": pair.target,
        }
    return {
        "family": str(pair.get("family", "")),
        "projectile": str(pair.get("projectile", "")),
        "target": str(pair.get("target", "")),
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}
