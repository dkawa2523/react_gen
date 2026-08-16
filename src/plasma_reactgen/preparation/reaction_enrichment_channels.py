from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.identifiers import pair_filename
from plasma_reactgen.domain.models import (
    CollisionPair,
    ReactionChannel,
    Species,
    SpeciesAmount,
)
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.validation.validators import validate_reaction


def iter_provider_channels(
    providers: list[Any],
    pair: CollisionPair,
) -> Iterator[dict[str, Any]]:
    for provider in providers:
        find_channels = getattr(provider, "find_channels", None)
        if callable(find_channels):
            yield from find_channels(pair)


def existing_channel_ids(
    registry: FileRegistry,
    pair: CollisionPair,
) -> set[str]:
    return {channel.id for channel in registry.get_channels(pair)}


def normalize_channel(raw_channel: dict[str, Any]) -> dict[str, Any]:
    channel = deepcopy(raw_channel)
    channel.pop("pair", None)
    channel.setdefault("status", "imported")
    channel.setdefault("data", {})
    source_record = channel.get("source_record")
    if source_record is not None:
        channel["data"].setdefault("source_record", source_record)
    channel["data"].setdefault(
        "provenance",
        channel["data"].get("source_record"),
    )
    return channel


def validate_channel(
    pair: CollisionPair,
    channel: dict[str, Any],
    species: dict[str, Species],
) -> dict[str, str]:
    reaction = _reaction_channel(channel)
    return validate_reaction(
        reactants=[SpeciesAmount(pair.projectile), SpeciesAmount(pair.target)],
        products=reaction.products,
        species=species,
    )


def append_channels(
    prepared_registry: Path,
    pair: CollisionPair,
    channels: list[dict[str, Any]],
) -> None:
    path = (
        prepared_registry / "reactions" / pair.family / pair_filename(pair.projectile, pair.target)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _reaction_file_payload(path, pair)
    payload.setdefault("channels", []).extend(channels)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _reaction_channel(channel: dict[str, Any]) -> ReactionChannel:
    return ReactionChannel(
        id=channel["id"],
        type=channel["type"],
        products=[
            SpeciesAmount(species=item["species"], n=float(item.get("n", 1.0)))
            for item in channel.get("products", [])
        ],
        threshold_eV=channel.get("threshold_eV"),
        deltaE_products_minus_reactants_eV=channel.get("deltaE_products_minus_reactants_eV"),
        dnt_class=channel.get("dnt_class"),
        data=channel.get("data", {}),
        status=channel.get("status", "imported"),
    )


def _reaction_file_payload(path: Path, pair: CollisionPair) -> dict[str, Any]:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "schema_version": 1,
        "pair": {
            "family": pair.family,
            "projectile": pair.projectile,
            "target": pair.target,
        },
        "channels": [],
        "metadata": {
            "status": "prepared",
            "notes": ["Prepared reaction enrichment; curated registry was not mutated."],
        },
    }


__all__ = [
    "append_channels",
    "existing_channel_ids",
    "iter_provider_channels",
    "normalize_channel",
    "validate_channel",
]
