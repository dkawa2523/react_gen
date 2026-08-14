"""Assemble and atomically publish portable registry packs."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from external_data_tools.cache import safe_filename
from external_data_tools.registry_admin_io import read_yaml, write_yaml
from external_data_tools.registry_pack_plan import analyze_registry_pack
from external_data_tools.registry_pack_validation import validate_registry_pack_source
from external_data_tools.registry_records import (
    channel_assets,
    channel_sources,
    species_paths,
    unique_dicts,
    validate_redistribution_status,
)
from plasma_reactgen.infrastructure.file_registry import FileRegistry


def build_registry_pack(
    *,
    pack_id: str,
    version: str,
    seed_gases: list[str],
    max_depth: int,
    registry_root: str | Path,
    packs_root: str | Path = Path("registry_packs"),
    redistribution_status: str = "site-local",
) -> dict[str, Any]:
    validate_redistribution_status(redistribution_status)
    root = Path(registry_root)
    destination_root = Path(packs_root)
    validation = validate_registry_pack_source(root)
    if validation["errors"]:
        return _failed_build(pack_id, version, validation)

    plan, network, registry = analyze_registry_pack(seed_gases, max_depth, root)
    pack_root = destination_root / safe_filename(pack_id) / safe_filename(version)
    staging = pack_root.parent / f".{safe_filename(version)}.tmp"
    _prepare_staging(staging)
    supported_species = sorted(network.species)
    _copy_species(root, staging, supported_species)
    sources, excluded = _copy_reactions_and_assets(
        root,
        staging,
        registry,
        {reaction.source_pair_key for reaction in network.reactions},
        redistribution_status,
    )
    manifest = _pack_manifest(
        pack_id,
        version,
        seed_gases,
        max_depth,
        supported_species,
        sources,
        excluded,
        plan,
        redistribution_status,
        validation,
    )
    write_yaml(staging / "pack.yaml", manifest)
    _replace_directory(staging, pack_root)
    _update_pack_index(destination_root, manifest, pack_root)
    return {
        "schema_version": 1,
        "built": True,
        "pack_root": str(pack_root),
        "pack": manifest,
        "validation": validation,
    }


def _failed_build(
    pack_id: str,
    version: str,
    validation: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "built": False,
        "pack_id": pack_id,
        "version": version,
        "validation": validation,
    }


def _pack_manifest(
    pack_id: str,
    version: str,
    seed_gases: list[str],
    max_depth: int,
    supported_species: list[str],
    sources: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    plan: dict[str, Any],
    redistribution_status: str,
    validation: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": pack_id,
        "version": version,
        "seed_gases": list(seed_gases),
        "supported_species": supported_species,
        "recommended_max_depth": max_depth,
        "source_manifest": unique_dicts(sources),
        "data_coverage_summary": plan["summary"],
        "redistribution_status": redistribution_status,
        "excluded_numeric_assets": unique_dicts(excluded),
        "validation": validation,
    }


def _prepare_staging(staging: Path) -> None:
    if staging.exists():
        shutil.rmtree(staging)
    for relative in (
        "species",
        "reactions",
        "assets/cross_sections",
        "assets/rate_coefficients",
    ):
        (staging / relative).mkdir(parents=True)


def _copy_species(root: Path, staging: Path, species_ids: list[str]) -> None:
    paths = species_paths(root)
    for species_id in species_ids:
        path = paths.get(species_id)
        if path is not None:
            shutil.copy2(path, staging / "species" / path.name)


def _copy_reactions_and_assets(
    root: Path,
    staging: Path,
    registry: FileRegistry,
    pair_keys: set[str],
    redistribution_status: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for path in registry.iter_reaction_files():
        payload = read_yaml(path)
        pair = payload.get("pair", {})
        key = f"{pair.get('family')}|{pair.get('projectile')}|{pair.get('target')}"
        if key not in pair_keys:
            continue
        destination = staging / "reactions" / str(pair["family"]) / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        for channel in payload.get("channels", []):
            sources.extend(channel_sources(channel))
            for asset in channel_assets(channel):
                if not _copy_asset(root, staging, asset, redistribution_status):
                    excluded.append(asset)
    return sources, excluded


def _copy_asset(
    root: Path,
    staging: Path,
    asset: dict[str, Any],
    redistribution_status: str,
) -> bool:
    source = root / asset["path"]
    permitted = (
        redistribution_status == "permitted" and asset["redistribution_status"] == "permitted"
    )
    if not permitted or not source.is_file():
        return False
    target = staging / asset["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    metadata = source.with_suffix(".metadata.yaml")
    if metadata.is_file():
        shutil.copy2(metadata, target.with_suffix(".metadata.yaml"))
    return True


def _replace_directory(staging: Path, destination: Path) -> None:
    backup = destination.with_name(f".{destination.name}.old")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.rename(backup)
    try:
        staging.rename(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _update_pack_index(
    packs_root: Path,
    manifest: dict[str, Any],
    pack_root: Path,
) -> None:
    path = packs_root / "index.yaml"
    index = read_yaml(path) if path.is_file() else {"schema_version": 1, "packs": []}
    entry = {
        "id": manifest["id"],
        "version": manifest["version"],
        "path": pack_root.relative_to(packs_root).as_posix(),
        "seed_gases": manifest["seed_gases"],
        "redistribution_status": manifest["redistribution_status"],
    }
    packs = [
        item
        for item in index.setdefault("packs", [])
        if not (item.get("id") == entry["id"] and item.get("version") == entry["version"])
    ]
    packs.append(entry)
    index["packs"] = sorted(
        packs,
        key=lambda item: (str(item.get("id")), str(item.get("version"))),
    )
    write_yaml(path, index)
