"""Combine DNT pair-property and reaction-channel completeness."""

from __future__ import annotations

from typing import Any


def dnt_channel_missing_fields(
    *,
    reaction_type: str | None,
    dnt_class: str | None,
    threshold_eV: Any,
    delta_e_eV: Any,
) -> list[str]:
    """Return fields needed to make one DNT channel complete."""

    missing: list[str] = []
    if not dnt_class:
        missing.append("dnt_class")
    if threshold_eV is None and reaction_type != "elastic":
        missing.append("threshold_eV")
    if delta_e_eV is None:
        missing.append("deltaE_products_minus_reactants_eV")
    return missing


def build_complete_dnt_readiness(
    pair_property_readiness: dict[str, Any],
    channels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine pair properties and channel completeness into one status."""

    missing_properties = _flatten_property_missing(pair_property_readiness.get("missing", {}))
    dnt_channels = [channel for channel in channels if channel.get("dnt_class")]
    channel_warnings = [
        {
            "reaction_id": channel.get("reaction_id"),
            "fields": list(channel.get("missing_for_complete_dnt", [])),
        }
        for channel in dnt_channels
        if channel.get("missing_for_complete_dnt")
    ]
    return {
        "status": _complete_status(
            missing_properties,
            dnt_channels,
            channel_warnings,
        ),
        "scope": "pair_properties_and_channels",
        "missing_required_properties": missing_properties,
        "channel_warnings": channel_warnings,
    }


def _complete_status(
    missing_properties: list[str],
    dnt_channels: list[dict[str, Any]],
    channel_warnings: list[dict[str, Any]],
) -> str:
    if missing_properties:
        return "missing_required_data"
    if not dnt_channels:
        return "no_dnt_channels"
    return "ready_with_warnings" if channel_warnings else "ready"


def _flatten_property_missing(missing: Any) -> list[str]:
    if isinstance(missing, list):
        return [str(field) for field in missing]
    if not isinstance(missing, dict):
        return []
    return [
        f"{side}.{field}"
        for side, fields in missing.items()
        if isinstance(fields, list)
        for field in fields
    ]


__all__ = ["build_complete_dnt_readiness", "dnt_channel_missing_fields"]
