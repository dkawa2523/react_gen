"""Validate scientific and artifact contracts required for registry packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.registry_admin_io import read_yaml
from external_data_tools.registry_records import channel_sources, species_paths
from plasma_reactgen.domain.models import CollisionPair, SpeciesAmount
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.infrastructure.indexer import check_registry_details
from plasma_reactgen.validation.validators import validate_reaction


def validate_registry_pack_source(registry_root: str | Path) -> dict[str, list[str]]:
    root = Path(registry_root)
    details = check_registry_details(root, strict=True)
    errors = list(details["errors"])
    warnings = list(details["warnings"])
    registry = FileRegistry(root)
    species = {species_id: registry.get_species(species_id) for species_id in species_paths(root)}
    dataset_ids: dict[str, str] = {}
    for path in registry.iter_reaction_files():
        _validate_reaction_file(path, root, species, dataset_ids, errors, warnings)
    return {"errors": sorted(set(errors)), "warnings": sorted(set(warnings))}


def _validate_reaction_file(
    path: Path,
    root: Path,
    species: dict[str, Any],
    dataset_ids: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> None:
    payload = read_yaml(path)
    pair_data = payload.get("pair", {})
    pair = CollisionPair(
        str(pair_data.get("family")),
        str(pair_data.get("projectile")),
        str(pair_data.get("target")),
    )
    available_species = {key: value for key, value in species.items() if value is not None}
    for channel in payload.get("channels", []):
        _validate_channel(channel, pair, root, available_species, dataset_ids, errors, warnings)


def _validate_channel(
    channel: dict[str, Any],
    pair: CollisionPair,
    root: Path,
    species: dict[str, Any],
    dataset_ids: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> None:
    channel_id = channel.get("id")
    products = [
        SpeciesAmount(str(item.get("species")), float(item.get("n", 1)))
        for item in channel.get("products", [])
    ]
    validation = validate_reaction(
        [SpeciesAmount(pair.projectile), SpeciesAmount(pair.target)],
        products,
        species,
    )
    if "failed" in {validation.get("charge_balance"), validation.get("element_balance")}:
        errors.append(f"reaction {channel_id}: charge or element balance failed")
    if not channel_sources(channel):
        warnings.append(f"reaction {channel_id}: source metadata is missing")
    datasets = channel.get("data", {}).get("datasets", [])
    for dataset in datasets if isinstance(datasets, list) else []:
        _validate_dataset(dataset, str(channel_id), root, dataset_ids, errors, warnings)


def _validate_dataset(
    dataset: dict[str, Any],
    channel_id: str,
    root: Path,
    dataset_ids: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> None:
    dataset_id = dataset.get("id")
    _validate_dataset_id(dataset_id, channel_id, dataset_ids, errors)
    _validate_dataset_metadata(dataset, dataset_id, warnings, errors)
    _validate_dataset_asset(dataset, dataset_id, root, errors)


def _validate_dataset_id(
    dataset_id: Any,
    channel_id: str,
    dataset_ids: dict[str, str],
    errors: list[str],
) -> None:
    if not dataset_id:
        errors.append(f"reaction {channel_id}: dataset id is missing")
    elif str(dataset_id) in dataset_ids:
        errors.append(
            f"duplicate dataset id '{dataset_id}': {dataset_ids[str(dataset_id)]} and {channel_id}"
        )
    else:
        dataset_ids[str(dataset_id)] = channel_id


def _validate_dataset_metadata(
    dataset: dict[str, Any],
    dataset_id: Any,
    warnings: list[str],
    errors: list[str],
) -> None:
    if not dataset.get("unit") and dataset.get("kind") not in {"threshold", "reaction_energy"}:
        errors.append(f"dataset {dataset_id}: unit is missing")
    if not (dataset.get("source_record") or dataset.get("source")):
        warnings.append(f"dataset {dataset_id}: source metadata is missing")


def _validate_dataset_asset(
    dataset: dict[str, Any],
    dataset_id: Any,
    root: Path,
    errors: list[str],
) -> None:
    asset_path = dataset.get("path") or (dataset.get("asset") or {}).get("path")
    if asset_path and not (root / asset_path).is_file():
        errors.append(f"dataset {dataset_id}: asset does not exist: {asset_path}")
