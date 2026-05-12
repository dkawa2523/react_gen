from __future__ import annotations

import re


def to_file_key(species_id: str) -> str:
    """Convert a human-readable species id into a filesystem-friendly key.

    This function is intentionally simple and deterministic. The registry scan
    uses YAML contents as the source of truth, so this is mainly used for
    templates and suggested filenames.
    """
    key = species_id.strip()
    key = key.replace("+", "_p")
    key = key.replace("-", "_m")
    key = key.replace("*", "_star")
    key = key.replace("(", "_").replace(")", "")
    key = key.replace("[", "_").replace("]", "")
    key = key.replace(" ", "_")
    key = re.sub(r"[^A-Za-z0-9_]+", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    return key or "unknown"


def pair_filename(projectile: str, target: str) -> str:
    return f"{to_file_key(projectile)}__{to_file_key(target)}.yaml"
