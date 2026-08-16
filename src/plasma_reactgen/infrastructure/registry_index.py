from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.models import CollisionPair


@dataclass(frozen=True)
class RegistryIndex:
    species: dict[str, Path]
    reactions: dict[str, Path]
    pairs: dict[str, CollisionPair]
    species_pairs: dict[str, set[str]]


def build_registry_index(
    species_files: Iterable[Path],
    reaction_files: Iterable[Path],
) -> RegistryIndex:
    species = _index_species(species_files)
    reactions, pairs, species_pairs = _index_reactions(reaction_files)
    return RegistryIndex(
        species=species,
        reactions=reactions,
        pairs=pairs,
        species_pairs=species_pairs,
    )


def load_registry_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _index_species(paths: Iterable[Path]) -> dict[str, Path]:
    species: dict[str, Path] = {}
    for path in paths:
        species_id = load_registry_yaml(path).get("id")
        if species_id:
            _add_unique(species, species_id, path, "species id")
    return species


def _index_reactions(
    paths: Iterable[Path],
) -> tuple[dict[str, Path], dict[str, CollisionPair], dict[str, set[str]]]:
    reactions: dict[str, Path] = {}
    pairs: dict[str, CollisionPair] = {}
    species_pairs: dict[str, set[str]] = defaultdict(set)
    channel_paths: dict[str, Path] = {}

    for path in paths:
        data = load_registry_yaml(path)
        pair = _read_pair(data)
        if pair is None:
            continue

        _add_unique(reactions, pair.key, path, "reaction pair")
        _index_channel_ids(data.get("channels", []), path, channel_paths)
        pairs[pair.key] = pair
        species_pairs[pair.projectile].add(pair.key)
        species_pairs[pair.target].add(pair.key)

    return reactions, pairs, dict(species_pairs)


def _read_pair(data: dict[str, Any]) -> CollisionPair | None:
    pair_data = data.get("pair", {})
    if not pair_data:
        return None
    family = pair_data.get("family")
    projectile = pair_data.get("projectile")
    target = pair_data.get("target")
    if not all(isinstance(value, str) and value for value in (family, projectile, target)):
        return None
    return CollisionPair(family=family, projectile=projectile, target=target)


def _index_channel_ids(
    channels: list[dict[str, Any]],
    path: Path,
    channel_paths: dict[str, Path],
) -> None:
    for channel in channels:
        channel_id = channel.get("id") if isinstance(channel, dict) else None
        if channel_id:
            _add_unique(channel_paths, str(channel_id), path, "reaction channel id")


def _add_unique(index: dict[str, Path], key: str, path: Path, label: str) -> None:
    previous = index.get(key)
    if previous is not None:
        raise ValueError(f"duplicate {label} '{key}': {previous} and {path}")
    index[key] = path
