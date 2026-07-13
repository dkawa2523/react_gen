from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.dnt_task_builder import check_dnt_property_readiness
from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species


def is_channel_allowed(
    channel: ReactionChannel,
    config: CaseConfig,
    *,
    pair: CollisionPair | None = None,
    species: Mapping[str, Species] | None = None,
    asset_exists: Callable[[str | None], bool] | None = None,
) -> bool:
    """Return whether a channel may enter network generation."""

    if channel.status in config.data_policy.allowed_status:
        status_allowed = True
    elif channel.status != "inferred":
        return False
    elif not config.inference.enabled or not config.inference.include_inferred_reactions:
        return False
    else:
        score = _channel_confidence_score(channel)
        status_allowed = score is not None and score >= config.inference.min_confidence

    if not status_allowed:
        return False
    if (
        pair is not None
        and pair.family == "electron"
        and not config.data_policy.include_reactions_without_cross_section
        and not has_available_cross_section(channel, asset_exists)
    ):
        return False
    if (
        pair is not None
        and pair.family == "ion_neutral"
        and not config.data_policy.include_reactions_without_dnt_ready_properties
        and not _has_dnt_ready_pair_properties(pair, species)
    ):
        return False
    return True


def is_reaction_validation_allowed(
    validation: Mapping[str, str],
    config: CaseConfig,
) -> bool:
    """Return whether validation completeness satisfies the data policy.

    A failed balance check is never accepted.  With the default permissive
    policy, unknown checks remain eligible; strict mode requires every reported
    validation check to be known and successful.
    """

    if any(status == "failed" for status in validation.values()):
        return False
    if config.data_policy.include_incomplete_reactions:
        return True
    return bool(validation) and all(status == "ok" for status in validation.values())


def _channel_confidence_score(channel: ReactionChannel) -> float | None:
    confidence = channel.data.get("confidence", {})
    if isinstance(confidence, dict):
        confidence = confidence.get("score")
    try:
        return float(confidence)
    except (TypeError, ValueError):
        return None


def has_available_cross_section(
    channel: ReactionChannel,
    asset_exists: Callable[[str | None], bool] | None,
) -> bool:
    cross_section = channel.data.get("cross_section")
    if not isinstance(cross_section, Mapping):
        return False
    path = cross_section.get("path")
    if not isinstance(path, str) or not path.strip() or asset_exists is None:
        return False
    try:
        return bool(asset_exists(path))
    except (OSError, TypeError, ValueError):
        return False


def _has_dnt_ready_pair_properties(
    pair: CollisionPair,
    species: Mapping[str, Species] | None,
) -> bool:
    if species is None:
        return False
    ion = species.get(pair.projectile)
    neutral = species.get(pair.target)
    if ion is None or neutral is None:
        return False
    return check_dnt_property_readiness(ion=ion, neutral=neutral).get("status") == "ready"
