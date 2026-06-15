from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import csv
import json

import yaml

from plasma_reactgen.data_sources.base import (
    CrossSectionProvider,
    PropertyProvider,
    ReactionProvider,
    SpeciesProvider,
)
from plasma_reactgen.domain.models import CollisionPair


class InternalFileSpeciesProvider(SpeciesProvider):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._records = _load_records(self.root / "species" / "species")

    def find_species(self, query: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for record in self._records:
            aliases = [str(alias) for alias in record.get("aliases", [])]
            if query == record.get("id") or query in aliases:
                matches.append(_with_source_record(record, "internal_species", record.get("id")))
        return matches


class InternalFilePropertyProvider(PropertyProvider):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._records = _load_records(self.root / "properties" / "properties")

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        requested = set(names) if names is not None else None
        matches: list[dict[str, Any]] = []
        for record in self._records:
            property_name = record.get("property")
            if record.get("species") != species_id:
                continue
            if requested is not None and property_name not in requested:
                continue
            matches.append(_with_source_record(record, "internal_property", f"{species_id}:{property_name}"))
        return matches


class InternalFileReactionProvider(ReactionProvider):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._records = [
            *_load_reaction_records(self.root / "reactions" / "electron", "electron"),
            *_load_reaction_records(self.root / "reactions" / "ion_neutral", "ion_neutral"),
        ]

    def find_channels(self, pair: CollisionPair) -> list[dict[str, Any]]:
        pair_payload = _pair_payload(pair)
        matches: list[dict[str, Any]] = []
        for record in self._records:
            if record.get("pair") != pair_payload:
                continue
            channel = deepcopy(record)
            source_id = channel.get("id") or _pair_key(pair)
            channel["source_record"] = _source_record("internal_file_db", f"internal_reaction:{source_id}")
            matches.append(channel)
        return matches


class InternalFileCrossSectionProvider(CrossSectionProvider):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._records = _load_records(self.root / "cross_sections" / "index")

    def find_cross_sections(self, pair: CollisionPair | str | dict[str, Any]) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for record in self._records:
            if not _cross_section_matches(record, pair):
                continue
            candidate = deepcopy(record)
            path = candidate.get("path") or candidate.get("file")
            channel_id = candidate.get("channel_id") or candidate.get("reaction_id")
            if path is not None:
                candidate["path"] = str(path)
            candidate["status"] = candidate.get("status", "internal_file_registered")
            candidate["source_record"] = _source_record(
                "internal_file_db",
                f"internal_cross_section:{channel_id or path}",
            )
            matches.append(candidate)
        return matches


def _load_records(path_without_suffix: Path) -> list[dict[str, Any]]:
    path = _first_existing_path(path_without_suffix)
    if path is None:
        return []
    if path.suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            data = list(csv.DictReader(handle))
    else:
        data = []

    if data is None:
        return []
    if isinstance(data, dict):
        data = data.get("records", data.get("items", []))
    if not isinstance(data, list):
        raise ValueError(f"internal data file must contain a list of records: {path}")
    return [deepcopy(record) for record in data if isinstance(record, dict)]


def _load_reaction_records(path_without_suffix: Path, default_family: str) -> list[dict[str, Any]]:
    raw_records = _load_records(path_without_suffix)
    records: list[dict[str, Any]] = []
    for record in raw_records:
        pair = record.get("pair")
        if "channels" in record:
            for channel in record.get("channels", []):
                if not isinstance(channel, dict):
                    continue
                payload = _channel_candidate(pair, channel, default_family)
                records.append(payload)
        else:
            records.append(_channel_candidate(pair, record, default_family))
    return records


def _channel_candidate(
    pair: dict[str, Any] | None,
    channel: dict[str, Any],
    default_family: str,
) -> dict[str, Any]:
    payload = deepcopy(channel)
    payload["pair"] = _normalize_pair(pair or payload.get("pair") or {}, default_family)
    return payload


def _normalize_pair(pair: dict[str, Any], default_family: str) -> dict[str, str]:
    return {
        "family": str(pair.get("family", default_family)),
        "projectile": str(pair.get("projectile", pair.get("reactant_1", ""))),
        "target": str(pair.get("target", pair.get("reactant_2", ""))),
    }


def _first_existing_path(path_without_suffix: Path) -> Path | None:
    if path_without_suffix.suffix and path_without_suffix.exists():
        return path_without_suffix
    for suffix in (".yaml", ".yml", ".json", ".csv"):
        path = path_without_suffix.with_suffix(suffix)
        if path.exists():
            return path
    return None


def _with_source_record(
    record: dict[str, Any],
    source_prefix: str,
    source_id: Any,
) -> dict[str, Any]:
    candidate = deepcopy(record)
    candidate.setdefault(
        "source_record",
        _source_record("internal_file_db", f"{source_prefix}:{source_id}"),
    )
    return candidate


def _cross_section_matches(record: dict[str, Any], query: CollisionPair | str | dict[str, Any]) -> bool:
    if isinstance(query, str):
        return query in {record.get("channel_id"), record.get("reaction_id")}
    if isinstance(query, CollisionPair):
        pair = record.get("pair")
        if pair is None:
            return False
        return _normalize_pair(pair, query.family) == _pair_payload(query)
    if isinstance(query, dict):
        pair = record.get("pair")
        return pair is not None and _normalize_pair(pair, str(query.get("family", ""))) == query
    return False


def _pair_payload(pair: CollisionPair) -> dict[str, str]:
    return {
        "family": pair.family,
        "projectile": pair.projectile,
        "target": pair.target,
    }


def _pair_key(pair: CollisionPair) -> str:
    return f"{pair.family}:{pair.projectile}:{pair.target}"


def _source_record(source_type: str, source_id: str) -> dict[str, str]:
    return {
        "source_type": source_type,
        "source_id": source_id,
    }
