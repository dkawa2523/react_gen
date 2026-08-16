from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


def reaction_counts(
    reactions: list[dict[str, Any]],
    prepared_registry: Path | None,
) -> dict[str, int]:
    statuses = Counter(_reaction_status(reaction) for reaction in reactions)
    families = Counter(str(reaction.get("family")) for reaction in reactions)
    return {
        "total": len(reactions),
        "electron": families["electron"],
        "ion_neutral": families["ion_neutral"],
        "inferred": statuses["inferred"],
        "imported": statuses["imported"],
        "literature_supported": statuses["literature_supported"],
        "imported_or_literature": statuses["imported"] + statuses["literature_supported"],
        "with_cross_section": sum(
            _has_cross_section_asset(reaction, prepared_registry) for reaction in reactions
        ),
        "with_provenance": sum(_has_provenance(reaction) for reaction in reactions),
    }


def max_reaction_depth(reactions: list[dict[str, Any]]) -> int:
    depths = []
    for reaction in reactions:
        try:
            depths.append(int(reaction.get("depth", 0)))
        except (TypeError, ValueError):
            continue
    return max(depths, default=0)


def count_cross_section_assets(prepared_registry: Path | None) -> int:
    if prepared_registry is None:
        return 0
    assets = prepared_registry / "assets" / "cross_sections"
    return len(list(assets.glob("*.csv"))) if assets.exists() else 0


def fraction(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator > 0 else 0.0


def validation_error_count(
    reactions: list[dict[str, Any]],
    missing_data: list[dict[str, Any]],
) -> int:
    reaction_errors = sum(_reaction_has_validation_error(item) for item in reactions)
    missing_errors = sum(
        1 for item in missing_data if isinstance(item, dict) and item.get("severity") == "error"
    )
    return reaction_errors + missing_errors


def _reaction_status(reaction: dict[str, Any]) -> str | None:
    data_status = reaction.get("data_status")
    if not isinstance(data_status, dict):
        return None
    return data_status.get("reaction")


def _has_cross_section_asset(
    reaction: dict[str, Any],
    prepared_registry: Path | None,
) -> bool:
    if prepared_registry is None:
        return False
    data = reaction.get("data")
    if not isinstance(data, dict):
        return False
    cross_section = data.get("cross_section")
    return isinstance(cross_section, dict) and registry_asset_exists(
        prepared_registry,
        cross_section.get("path"),
    )


def _has_provenance(reaction: dict[str, Any]) -> bool:
    data = reaction.get("data")
    return isinstance(data, dict) and any(
        data.get(key) for key in ("provenance", "source_record", "evidence")
    )


def _reaction_has_validation_error(reaction: dict[str, Any]) -> bool:
    validation = reaction.get("validation")
    return isinstance(validation, dict) and any(
        value not in {"ok", None} for value in validation.values()
    )


__all__ = [
    "count_cross_section_assets",
    "fraction",
    "max_reaction_depth",
    "reaction_counts",
    "validation_error_count",
]
