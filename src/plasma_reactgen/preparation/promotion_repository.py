"""YAML repository access for reviewed registry promotion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.identifiers import pair_filename, to_file_key

PairRecord = dict[str, str]
YamlRecord = dict[str, Any]


def load_decisions(path: Path) -> list[Any]:
    payload = load_yaml(path)
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("promotion decision file must contain a decisions list")
    return decisions


def find_species_file(
    root: Path,
    species_id: str,
) -> tuple[Path, YamlRecord] | None:
    for path in sorted((root / "species").glob("*.yaml")):
        payload = load_yaml(path)
        if species_id in _species_ids(payload):
            return path, payload
    fallback = root / "species" / f"{to_file_key(species_id)}.yaml"
    return (fallback, load_yaml(fallback)) if fallback.exists() else None


def find_prepared_channel(
    prepared_registry: Path,
    channel_id: str,
    pair: PairRecord,
) -> tuple[Path, YamlRecord] | None:
    pair_path = reaction_pair_path(prepared_registry, pair)
    found = _channel_from_pair_file(pair_path, channel_id)
    if found is not None:
        return pair_path, found
    return _find_standalone_channel(prepared_registry, channel_id, pair)


def find_pair_file(root: Path, pair: PairRecord) -> Path | None:
    family_dir = root / "reactions" / pair["family"]
    for path in sorted(family_dir.glob("*.yaml")):
        if same_pair(load_yaml(path).get("pair", {}), pair):
            return path
    return None


def reaction_pair_path(root: Path, pair: PairRecord) -> Path:
    return root / "reactions" / pair["family"] / pair_filename(pair["projectile"], pair["target"])


def same_pair(candidate: Any, pair: PairRecord) -> bool:
    if not isinstance(candidate, dict):
        return False
    return all(str(candidate.get(key) or "") == value for key, value in pair.items())


def load_yaml(path: Path) -> YamlRecord:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def write_yaml(path: Path, payload: YamlRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _species_ids(payload: YamlRecord) -> set[str]:
    ids = {str(payload.get("id") or "")}
    if payload.get("display_id"):
        ids.add(str(payload["display_id"]))
    return ids


def _channel_from_pair_file(path: Path, channel_id: str) -> YamlRecord | None:
    if not path.exists():
        return None
    channels = load_yaml(path).get("channels", [])
    if not isinstance(channels, list):
        return None
    return next(
        (
            channel
            for channel in channels
            if isinstance(channel, dict) and channel.get("id") == channel_id
        ),
        None,
    )


def _find_standalone_channel(
    prepared_registry: Path,
    channel_id: str,
    pair: PairRecord,
) -> tuple[Path, YamlRecord] | None:
    for path in sorted((prepared_registry / "reactions").glob("*.yaml")):
        payload = load_yaml(path)
        if payload.get("id") == channel_id and same_pair(payload.get("pair"), pair):
            return path, payload
    return None


__all__ = [
    "PairRecord",
    "find_pair_file",
    "find_prepared_channel",
    "find_species_file",
    "load_decisions",
    "load_yaml",
    "reaction_pair_path",
    "same_pair",
    "write_yaml",
]
