from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_lxcat_mappings(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("LXCat mapping manifest must be a YAML mapping")
    mappings = payload.get("mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("LXCat mapping manifest must contain a mappings list")
    return [mapping for mapping in mappings if isinstance(mapping, dict)]


def find_lxcat_mapping(
    mappings: list[dict[str, Any]],
    *,
    target: str,
    process_label: str | None,
) -> dict[str, Any] | None:
    label = (process_label or "").lower()
    for mapping in mappings:
        if str(mapping.get("target") or "") != target:
            continue
        contains = mapping.get("process_label_contains")
        if contains and str(contains).lower() not in label:
            continue
        if mapping.get("reaction_id"):
            return mapping
    return None


def update_prepared_electron_channel(
    prepared_registry: Path,
    *,
    reaction_id: str,
    asset_path: str,
    source: str,
    process_label_original: str | None,
    mapping_status: str | None = None,
) -> list[Path]:
    prepared_registry = Path(prepared_registry)
    reaction_root = prepared_registry / "reactions" / "electron"
    if not reaction_root.exists():
        return []

    updated: list[Path] = []
    for path in sorted(reaction_root.glob("*.yaml")):
        if _update_reaction_file(
            path,
            reaction_id=reaction_id,
            asset_path=asset_path,
            source=source,
            process_label_original=process_label_original,
            mapping_status=mapping_status,
        ):
            updated.append(path)
    return updated


def _update_reaction_file(
    path: Path,
    *,
    reaction_id: str,
    asset_path: str,
    source: str,
    process_label_original: str | None,
    mapping_status: str | None,
) -> bool:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    channels = payload.get("channels", [])
    changed = False
    for channel in channels if isinstance(channels, list) else []:
        if isinstance(channel, dict) and channel.get("id") == reaction_id:
            _register_cross_section(
                channel,
                asset_path=asset_path,
                source=source,
                process_label_original=process_label_original,
                mapping_status=mapping_status,
            )
            changed = True
    if changed:
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return changed


def _register_cross_section(
    channel: dict[str, Any],
    *,
    asset_path: str,
    source: str,
    process_label_original: str | None,
    mapping_status: str | None,
) -> None:
    data = channel.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        channel["data"] = data
    cross_section = data.setdefault("cross_section", {})
    if not isinstance(cross_section, dict):
        cross_section = {}
        data["cross_section"] = cross_section
    cross_section.update(
        {
            "status": "local_file_registered",
            "path": asset_path,
            "format": "csv_energy_eV_sigma_m2",
            "source": source,
        }
    )
    if mapping_status:
        cross_section["mapping_status"] = mapping_status
    if process_label_original:
        cross_section["process_label_original"] = process_label_original
