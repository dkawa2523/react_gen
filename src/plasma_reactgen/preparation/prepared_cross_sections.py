from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def apply_cross_section_to_reactions(
    prepared_registry: Path,
    reaction_id: str,
    cross_section_fields: dict[str, Any],
) -> list[Path]:
    reaction_root = prepared_registry / "reactions" / "electron"
    if not reaction_root.exists():
        return []

    updated = []
    for path in sorted(reaction_root.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if _update_reaction_payload(payload, reaction_id, cross_section_fields):
            _write_yaml(path, payload)
            updated.append(path)
    return updated


def _update_reaction_payload(
    payload: dict[str, Any],
    reaction_id: str,
    cross_section_fields: dict[str, Any],
) -> bool:
    changed = False
    for channel in payload.get("channels", []):
        if not isinstance(channel, dict) or channel.get("id") != reaction_id:
            continue
        data = channel.setdefault("data", {})
        cross_section = data.get("cross_section")
        if not isinstance(cross_section, dict):
            cross_section = {}
            data["cross_section"] = cross_section
        cross_section.update(cross_section_fields)
        changed = True
    return changed


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
