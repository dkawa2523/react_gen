"""Shared registry record lookup and dataset mutation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from external_data_tools.registry_admin_io import read_yaml, write_yaml
from plasma_reactgen.domain.equations import format_equation
from plasma_reactgen.domain.models import SpeciesAmount

REDISTRIBUTION_VALUES = {"permitted", "internal", "site-local"}

__all__ = [
    "REDISTRIBUTION_VALUES",
    "append_dataset",
    "channel_assets",
    "channel_records",
    "channel_sources",
    "exact_channel_matches",
    "species_paths",
    "unique_dicts",
    "validate_redistribution_status",
]


def validate_redistribution_status(value: str) -> None:
    if value not in REDISTRIBUTION_VALUES:
        raise ValueError(f"unsupported redistribution status: {value}")


def species_paths(registry_root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted((registry_root / "species").glob("*.yaml")):
        payload = read_yaml(path)
        if isinstance(payload, dict) and payload.get("id"):
            result[str(payload["id"])] = path
    return result


def channel_records(registry_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((registry_root / "reactions").glob("*/*.yaml")):
        payload = read_yaml(path)
        if not isinstance(payload, dict):
            continue
        pair = payload.get("pair", {})
        reactants = [
            SpeciesAmount(str(pair.get("projectile"))),
            SpeciesAmount(str(pair.get("target"))),
        ]
        for index, channel in enumerate(payload.get("channels", [])):
            products = [
                SpeciesAmount(str(item.get("species")), float(item.get("n", 1)))
                for item in channel.get("products", [])
            ]
            records.append(
                {
                    "reaction_id": str(channel.get("id") or ""),
                    "equation": format_equation(reactants, products),
                    "path": path,
                    "channel_index": index,
                }
            )
    return records


def exact_channel_matches(
    record: dict[str, Any],
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reaction_id = str(record.get("reaction_id") or "").strip()
    if reaction_id:
        return [channel for channel in channels if channel["reaction_id"] == reaction_id]
    equation = normalize_equation(record.get("equation") or record.get("reaction"))
    if not equation:
        return []
    return [channel for channel in channels if normalize_equation(channel["equation"]) == equation]


def normalize_equation(value: Any) -> str:
    return " ".join(str(value or "").replace("=>", "->").split())


def append_dataset(match: dict[str, Any], dataset: dict[str, Any]) -> bool:
    path = Path(match["path"])
    payload = read_yaml(path)
    channel = payload["channels"][match["channel_index"]]
    datasets = channel.setdefault("data", {}).setdefault("datasets", [])
    if any(item.get("id") == dataset["id"] for item in datasets if isinstance(item, dict)):
        return False
    datasets.append(dataset)
    write_yaml(path, payload)
    return True


def channel_sources(channel: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [
        dict(value)
        for value in (
            channel.get("source_record"),
            channel.get("provenance"),
            channel.get("evidence"),
        )
        if isinstance(value, dict) and value
    ]
    data = channel.get("data", {})
    datasets = data.get("datasets", []) if isinstance(data, dict) else []
    for dataset in datasets:
        source = dataset.get("source_record") or dataset.get("source")
        if isinstance(source, dict) and source:
            sources.append(dict(source))
        elif source:
            sources.append({"source": source})
    return sources


def channel_assets(channel: dict[str, Any]) -> list[dict[str, Any]]:
    data = channel.get("data", {})
    if not isinstance(data, dict):
        return []
    assets = _legacy_assets(data)
    datasets = data.get("datasets", [])
    if not isinstance(datasets, list):
        return assets
    assets.extend(
        asset
        for dataset in datasets
        if isinstance(dataset, dict)
        if (asset := _dataset_asset(dataset)) is not None
    )
    return assets


def _legacy_assets(data: dict[str, Any]) -> list[dict[str, Any]]:
    cross_section = data.get("cross_section")
    if not isinstance(cross_section, dict) or not cross_section.get("path"):
        return []
    return [
        {
            "path": str(cross_section["path"]),
            "kind": "cross_section",
            "redistribution_status": str(
                cross_section.get("redistribution_status") or "site-local"
            ),
        }
    ]


def _dataset_asset(dataset: dict[str, Any]) -> dict[str, Any] | None:
    nested_asset = dataset.get("asset")
    path = dataset.get("path") or (
        nested_asset.get("path") if isinstance(nested_asset, dict) else None
    )
    if not path:
        return None
    source = dataset.get("source_record") or dataset.get("source") or {}
    redistribution = (
        source.get("redistribution_status")
        if isinstance(source, dict)
        else dataset.get("redistribution_status")
    )
    return {
        "path": str(path),
        "kind": str(dataset.get("kind") or "unknown"),
        "redistribution_status": str(redistribution or "site-local"),
    }


def unique_dicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = yaml.safe_dump(record, sort_keys=True, allow_unicode=True)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result
