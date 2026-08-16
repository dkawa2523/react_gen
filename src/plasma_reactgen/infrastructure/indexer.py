from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


def check_registry_details(
    registry_root: str | Path,
    strict: bool = False,
) -> dict[str, list[str]]:
    registry_root = Path(registry_root)
    if not registry_root.is_dir():
        return {
            "errors": [f"registry root does not exist or is not a directory: {registry_root}"],
            "warnings": [],
        }

    species_root = registry_root / "species"
    reaction_root = registry_root / "reactions"
    errors = _layout_errors(registry_root, species_root, reaction_root)
    warnings: list[str] = []
    species_ids = _scan_species(species_root, errors)
    _scan_reactions(
        registry_root,
        reaction_root,
        species_ids,
        errors,
        warnings,
        strict=strict,
    )
    return {"errors": errors, "warnings": warnings}


def _layout_errors(registry_root: Path, species_root: Path, reaction_root: Path) -> list[str]:
    errors = []
    for path, label in ((species_root, "species"), (reaction_root, "reactions")):
        if not path.is_dir():
            errors.append(f"registry {label} directory is missing: {path}")
    for required_rule in ("reaction_type_catalog.yaml", "role_required_properties.yaml"):
        path = registry_root / "rules" / required_rule
        if not path.is_file():
            errors.append(f"required registry rule is missing: {path}")
    return errors


def _scan_species(species_root: Path, errors: list[str]) -> set[str]:
    species_ids: set[str] = set()
    species_paths: dict[str, Path] = {}
    for path in sorted(species_root.glob("*.yaml")):
        try:
            _validate_species_file(path, _read_yaml(path), species_ids, species_paths, errors)
        except Exception as exc:
            errors.append(f"species {path}: {exc}")
    return species_ids


def _validate_species_file(
    path: Path,
    data: dict[str, Any],
    species_ids: set[str],
    species_paths: dict[str, Path],
    errors: list[str],
) -> None:
    for field in ("id", "composition", "charge", "classes"):
        if field not in data:
            errors.append(f"species {path}: missing required field '{field}'")
    if not data.get("id"):
        return
    species_id = str(data["id"])
    if species_id in species_paths:
        errors.append(
            f"duplicate species id '{species_id}': {species_paths[species_id]} and {path}"
        )
    species_paths[species_id] = path
    species_ids.add(species_id)


def _scan_reactions(
    registry_root: Path,
    reaction_root: Path,
    species_ids: set[str],
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool,
) -> None:
    pair_paths: dict[str, Path] = {}
    channel_paths: dict[str, Path] = {}
    for path in sorted(reaction_root.glob("*/*.yaml")):
        try:
            _validate_reaction_file(
                registry_root,
                path,
                _read_yaml(path),
                species_ids,
                pair_paths,
                channel_paths,
                errors,
                warnings,
                strict=strict,
            )
        except Exception as exc:
            errors.append(f"reaction {path}: {exc}")


def _validate_reaction_file(
    registry_root: Path,
    path: Path,
    data: dict[str, Any],
    species_ids: set[str],
    pair_paths: dict[str, Path],
    channel_paths: dict[str, Path],
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool,
) -> None:
    pair = data.get("pair", {})
    _validate_pair(path, pair, species_ids, pair_paths, errors)
    for channel in data.get("channels", []):
        _validate_channel(
            registry_root,
            path,
            channel,
            species_ids,
            channel_paths,
            errors,
            warnings,
            strict=strict,
        )


def _validate_pair(
    path: Path,
    pair: dict[str, Any],
    species_ids: set[str],
    pair_paths: dict[str, Path],
    errors: list[str],
) -> None:
    for field in ("family", "projectile", "target"):
        if field not in pair:
            errors.append(f"reaction {path}: pair missing '{field}'")
    if all(pair.get(field) for field in ("family", "projectile", "target")):
        pair_key = f"{pair['family']}|{pair['projectile']}|{pair['target']}"
        if pair_key in pair_paths:
            errors.append(
                f"duplicate reaction pair '{pair_key}': {pair_paths[pair_key]} and {path}"
            )
        pair_paths[pair_key] = path
    for species_id in (pair.get("projectile"), pair.get("target")):
        if species_id and species_id != "e" and species_id not in species_ids:
            errors.append(f"reaction {path}: reactant species not registered: {species_id}")


def _validate_channel(
    registry_root: Path,
    path: Path,
    channel: dict[str, Any],
    species_ids: set[str],
    channel_paths: dict[str, Path],
    errors: list[str],
    warnings: list[str],
    *,
    strict: bool,
) -> None:
    _validate_channel_id(path, channel, channel_paths, errors)
    destinations = errors if strict else warnings
    for product in channel.get("products", []):
        species_id = product.get("species")
        if species_id and species_id != "e" and species_id not in species_ids:
            destinations.append(f"reaction {path}: product species not registered: {species_id}")
    cross_section = channel.get("data", {}).get("cross_section")
    if (
        cross_section
        and cross_section.get("path")
        and not registry_asset_exists(registry_root, cross_section["path"])
    ):
        destinations.append(
            f"reaction {path}: cross-section path does not exist: {cross_section['path']}"
        )


def _validate_channel_id(
    path: Path,
    channel: dict[str, Any],
    channel_paths: dict[str, Path],
    errors: list[str],
) -> None:
    channel_id = channel.get("id")
    if not channel_id:
        errors.append(f"reaction {path}: channel missing 'id'")
        return
    channel_id = str(channel_id)
    if channel_id in channel_paths:
        errors.append(
            f"duplicate reaction channel id '{channel_id}': {channel_paths[channel_id]} and {path}"
        )
    channel_paths[channel_id] = path


def format_registry_check(details: dict[str, list[str]]) -> str:
    errors = details.get("errors", [])
    warnings = details.get("warnings", [])

    lines = ["Registry check report"]
    lines.append(f"  errors: {len(errors)}")
    lines.append(f"  warnings: {len(warnings)}")
    if errors:
        lines.append("\nErrors:")
        lines.extend(f"  - {x}" for x in errors)
    if warnings:
        lines.append("\nWarnings:")
        lines.extend(f"  - {x}" for x in warnings)
    return "\n".join(lines)


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
