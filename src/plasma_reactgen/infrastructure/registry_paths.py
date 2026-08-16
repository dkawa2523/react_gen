from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_registry_asset(registry_root: str | Path, relative_path: Any) -> Path | None:
    """Resolve an asset path only when it remains inside the registry root."""

    if not isinstance(relative_path, (str, Path)):
        return None
    path = Path(relative_path)
    if path.is_absolute() or not path.parts:
        return None

    try:
        root = Path(registry_root).resolve()
        candidate = (root / path).resolve()
    except (OSError, RuntimeError):
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def registry_asset_exists(registry_root: str | Path, relative_path: Any) -> bool:
    """Return whether a registry-relative path identifies an existing file."""

    candidate = resolve_registry_asset(registry_root, relative_path)
    return candidate is not None and candidate.is_file()
