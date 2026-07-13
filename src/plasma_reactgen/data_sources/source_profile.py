from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_source_profile(path_or_name: str | Path | None, registry_root: Path) -> dict[str, Any]:
    """Load a source profile from an explicit path or the registry.

    Profile contents live in YAML only. Unknown names fail visibly instead of
    silently changing the requested enrichment policy to ``local_only``.
    """

    profile = Path(path_or_name) if path_or_name is not None else Path("local_only")
    if not profile.exists():
        profile = Path(registry_root) / "rules" / "source_profiles" / f"{profile}.yaml"
    if not profile.is_file():
        raise ValueError(f"source profile does not exist: {path_or_name or 'local_only'}")
    return _read_profile(profile)


def _read_profile(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"source profile is not valid YAML: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"source profile must be a YAML mapping: {path}")
    return data
