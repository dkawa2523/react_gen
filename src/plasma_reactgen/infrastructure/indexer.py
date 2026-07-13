from __future__ import annotations

from pathlib import Path
import yaml

from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


def check_registry_details(registry_root: str | Path, strict: bool = False) -> dict[str, list[str]]:
    registry_root = Path(registry_root)
    errors: list[str] = []
    warnings: list[str] = []

    if not registry_root.is_dir():
        return {
            "errors": [f"registry root does not exist or is not a directory: {registry_root}"],
            "warnings": [],
        }

    species_root = registry_root / "species"
    reaction_root = registry_root / "reactions"
    if not species_root.is_dir():
        errors.append(f"registry species directory is missing: {species_root}")
    if not reaction_root.is_dir():
        errors.append(f"registry reactions directory is missing: {reaction_root}")
    for required_rule in ("reaction_type_catalog.yaml", "role_required_properties.yaml"):
        path = registry_root / "rules" / required_rule
        if not path.is_file():
            errors.append(f"required registry rule is missing: {path}")

    species_ids: set[str] = set()
    species_paths: dict[str, Path] = {}
    for path in sorted(species_root.glob("*.yaml")):
        try:
            data = _read_yaml(path)
            for field in ["id", "composition", "charge", "classes"]:
                if field not in data:
                    errors.append(f"species {path}: missing required field '{field}'")
            if data.get("id"):
                species_id = str(data["id"])
                if species_id in species_paths:
                    errors.append(
                        f"duplicate species id '{species_id}': {species_paths[species_id]} and {path}"
                    )
                species_paths[species_id] = path
                species_ids.add(species_id)
        except Exception as exc:  # noqa: BLE001 - registry check should collect readable errors
            errors.append(f"species {path}: {exc}")

    pair_paths: dict[str, Path] = {}
    channel_paths: dict[str, Path] = {}
    for path in sorted(reaction_root.glob("*/*.yaml")):
        try:
            data = _read_yaml(path)
            pair = data.get("pair", {})
            for field in ["family", "projectile", "target"]:
                if field not in pair:
                    errors.append(f"reaction {path}: pair missing '{field}'")
            if all(pair.get(field) for field in ("family", "projectile", "target")):
                pair_key = f"{pair['family']}|{pair['projectile']}|{pair['target']}"
                if pair_key in pair_paths:
                    errors.append(
                        f"duplicate reaction pair '{pair_key}': {pair_paths[pair_key]} and {path}"
                    )
                pair_paths[pair_key] = path
            for sid in [pair.get("projectile"), pair.get("target")]:
                if sid and sid != "e" and sid not in species_ids:
                    errors.append(f"reaction {path}: reactant species not registered: {sid}")
            for channel in data.get("channels", []):
                channel_id = channel.get("id")
                if not channel_id:
                    errors.append(f"reaction {path}: channel missing 'id'")
                else:
                    channel_id = str(channel_id)
                    if channel_id in channel_paths:
                        errors.append(
                            f"duplicate reaction channel id '{channel_id}': "
                            f"{channel_paths[channel_id]} and {path}"
                        )
                    channel_paths[channel_id] = path
                for product in channel.get("products", []):
                    sid = product.get("species")
                    if sid and sid != "e" and sid not in species_ids:
                        msg = f"reaction {path}: product species not registered: {sid}"
                        (errors if strict else warnings).append(msg)
                cs = channel.get("data", {}).get("cross_section")
                if cs and cs.get("path") and not registry_asset_exists(registry_root, cs["path"]):
                    msg = f"reaction {path}: cross-section path does not exist: {cs['path']}"
                    (errors if strict else warnings).append(msg)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reaction {path}: {exc}")

    return {"errors": errors, "warnings": warnings}


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


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
