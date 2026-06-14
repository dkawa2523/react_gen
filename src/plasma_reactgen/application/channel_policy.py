from __future__ import annotations

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import ReactionChannel


def is_channel_allowed(channel: ReactionChannel, config: CaseConfig) -> bool:
    """Return whether a channel may enter network generation."""

    if channel.status in config.data_policy.exclude_status:
        return False
    if channel.status in config.data_policy.allowed_status:
        return True
    if channel.status != "inferred":
        return False
    if not config.inference.enabled or not config.inference.include_inferred_reactions:
        return False
    score = _channel_confidence_score(channel)
    return score is not None and score >= config.inference.min_confidence


def _channel_confidence_score(channel: ReactionChannel) -> float | None:
    confidence = channel.data.get("confidence", {})
    if isinstance(confidence, dict):
        confidence = confidence.get("score")
    try:
        return float(confidence)
    except (TypeError, ValueError):
        return None
