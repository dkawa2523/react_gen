from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RegistryPackInfo:
    id: str
    version: str
    root: Path
    seed_gases: tuple[str, ...]
    recommended_max_depth: int | None
    redistribution_status: str

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "seed_gases": list(self.seed_gases),
            "recommended_max_depth": self.recommended_max_depth,
            "redistribution_status": self.redistribution_status,
        }


def select_registry_pack(
    gases: list[str],
    packs_root: str | Path,
) -> RegistryPackInfo | None:
    root = Path(packs_root)
    index_path = root / "index.yaml"
    if not index_path.is_file():
        return None

    required = set(gases)
    candidates = [
        pack
        for entry in _pack_entries(index_path)
        if (pack := _pack_info(root, entry, required)) is not None
    ]
    return min(candidates, key=lambda pack: _selection_key(pack, required), default=None)


def _pack_entries(index_path: Path) -> list[dict[str, Any]]:
    entries = _read_yaml(index_path).get("packs", [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")]


def _pack_info(
    packs_root: Path,
    entry: dict[str, Any],
    required: set[str],
) -> RegistryPackInfo | None:
    pack_root = _pack_root(packs_root, str(entry.get("path") or entry["id"]))
    if pack_root is None:
        return None
    manifest_path = pack_root / "pack.yaml"
    if not manifest_path.is_file():
        return None

    manifest = {**entry, **_read_yaml(manifest_path)}
    seed_gases = tuple(str(value) for value in manifest.get("seed_gases", []))
    if not required.issubset(seed_gases):
        return None
    return RegistryPackInfo(
        id=str(manifest["id"]),
        version=str(manifest.get("version") or "0"),
        root=pack_root,
        seed_gases=seed_gases,
        recommended_max_depth=_optional_int(manifest.get("recommended_max_depth")),
        redistribution_status=str(manifest.get("redistribution_status") or "site-local"),
    )


def _pack_root(packs_root: Path, relative_path: str) -> Path | None:
    candidate = packs_root / relative_path
    try:
        candidate.resolve().relative_to(packs_root.resolve())
    except ValueError:
        return None
    return candidate


def _selection_key(pack: RegistryPackInfo, required: set[str]) -> tuple[Any, ...]:
    return (
        len(set(pack.seed_gases) - required),
        tuple(-value for value in _version_key(pack.version)),
        pack.id,
    )


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for value in version.split("."):
        try:
            parts.append(int(value))
        except ValueError:
            parts.append(0)
    return tuple([*parts, 0, 0, 0, 0][:4])


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}
