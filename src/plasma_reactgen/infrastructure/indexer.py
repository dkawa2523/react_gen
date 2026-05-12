from __future__ import annotations

from pathlib import Path
import yaml


def build_indexes(registry_root: str | Path) -> None:
    registry_root = Path(registry_root)
    index_dir = registry_root / "index"
    index_dir.mkdir(parents=True, exist_ok=True)

    species_index = {}
    for path in sorted((registry_root / "species").glob("*.yaml")):
        data = _read_yaml(path)
        if data.get("id"):
            species_index[data["id"]] = str(path.relative_to(registry_root))

    reaction_index = {}
    reaction_root = registry_root / "reactions"
    if reaction_root.exists():
        for path in sorted(reaction_root.glob("*/*.yaml")):
            data = _read_yaml(path)
            pair = data.get("pair", {})
            if pair:
                key = f"{pair.get('family')}|{pair.get('projectile')}|{pair.get('target')}"
                reaction_index[key] = str(path.relative_to(registry_root))

    _write_yaml(index_dir / "species_index.yaml", {"schema_version": 1, "species": species_index})
    _write_yaml(index_dir / "reaction_pair_index.yaml", {"schema_version": 1, "pairs": reaction_index})


def check_registry(registry_root: str | Path, strict: bool = False) -> str:
    registry_root = Path(registry_root)
    errors: list[str] = []
    warnings: list[str] = []

    species_ids: set[str] = set()
    for path in sorted((registry_root / "species").glob("*.yaml")):
        try:
            data = _read_yaml(path)
            for field in ["id", "composition", "charge", "classes"]:
                if field not in data:
                    errors.append(f"species {path}: missing required field '{field}'")
            if data.get("id"):
                species_ids.add(data["id"])
        except Exception as exc:  # noqa: BLE001 - registry check should collect readable errors
            errors.append(f"species {path}: {exc}")

    for path in sorted((registry_root / "reactions").glob("*/*.yaml")):
        try:
            data = _read_yaml(path)
            pair = data.get("pair", {})
            for field in ["family", "projectile", "target"]:
                if field not in pair:
                    errors.append(f"reaction {path}: pair missing '{field}'")
            for sid in [pair.get("projectile"), pair.get("target")]:
                if sid and sid != "e" and sid not in species_ids:
                    errors.append(f"reaction {path}: reactant species not registered: {sid}")
            for channel in data.get("channels", []):
                for product in channel.get("products", []):
                    sid = product.get("species")
                    if sid and sid != "e" and sid not in species_ids:
                        msg = f"reaction {path}: product species not registered: {sid}"
                        (errors if strict else warnings).append(msg)
                cs = channel.get("data", {}).get("cross_section")
                if cs and cs.get("path") and not (registry_root / cs["path"]).exists():
                    msg = f"reaction {path}: cross-section path does not exist: {cs['path']}"
                    (errors if strict else warnings).append(msg)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reaction {path}: {exc}")

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


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
