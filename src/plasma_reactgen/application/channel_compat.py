from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plasma_reactgen.domain.models import ReactionChannel


def legacy_cross_section(channel: ReactionChannel) -> Mapping[str, Any] | None:
    """Expose the old data.cross_section shape only at the compatibility edge."""

    value = channel.data.get("cross_section")
    return value if isinstance(value, Mapping) else None


def confidence_value(channel: ReactionChannel) -> Any:
    """Prefer normalized confidence and fall back to legacy channel data."""

    if channel.confidence is not None:
        return channel.confidence
    return channel.data.get("confidence")


def confidence_score(channel: ReactionChannel) -> float | None:
    """Return one normalized numeric confidence score for all callers."""

    value = confidence_value(channel)
    if isinstance(value, Mapping):
        value = value.get("score")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
