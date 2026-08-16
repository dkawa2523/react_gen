"""Summarize numerical-data availability for generated reactions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plasma_reactgen.application.channel_compat import legacy_cross_section
from plasma_reactgen.application.channel_policy import has_available_cross_section
from plasma_reactgen.application.reaction_catalog import AssetExists
from plasma_reactgen.domain.datasets import ReactionDataset
from plasma_reactgen.domain.models import ReactionChannel


def reaction_data_status(
    channel: ReactionChannel,
    family: str,
    asset_exists: AssetExists | None = None,
) -> dict[str, str]:
    """Return normalized status without hiding legacy channel data."""

    status = {"reaction": channel.status}
    if family == "electron":
        status["cross_section"] = electron_cross_section_status(
            channel,
            asset_exists,
        )
    elif family == "ion_neutral":
        status["dnt_class"] = "inferred" if channel.status == "inferred" else "registered"
    return status


def electron_cross_section_status(
    channel: ReactionChannel,
    asset_exists: AssetExists | None = None,
) -> str:
    legacy = legacy_cross_section(channel)
    datasets = [dataset for dataset in channel.datasets if dataset.kind == "cross_section"]
    if not legacy and not datasets:
        return "missing"
    if has_available_cross_section(channel, asset_exists):
        return "local_file_registered"
    if _has_registered_path(legacy, datasets):
        return "path_registered_but_missing"
    return (
        str(legacy.get("status", "reference_only_needs_import"))
        if legacy is not None
        else "reference_only_needs_import"
    )


def _has_registered_path(
    legacy: Mapping[str, Any] | None,
    datasets: list[ReactionDataset],
) -> bool:
    return bool(
        (legacy is not None and legacy.get("path"))
        or any(dataset.asset and dataset.asset.path for dataset in datasets)
    )


__all__ = ["electron_cross_section_status", "reaction_data_status"]
