from __future__ import annotations

from collections.abc import Callable, Mapping

from plasma_reactgen.application.channel_compat import confidence_score, legacy_cross_section
from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.dnt_properties import check_dnt_property_readiness
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

    if not _status_allowed(channel, config):
        return False
    return pair is None or _pair_data_allowed(
        channel,
        pair,
        config,
        species=species,
        asset_exists=asset_exists,
    )


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


def has_available_cross_section(
    channel: ReactionChannel,
    asset_exists: Callable[[str | None], bool] | None,
) -> bool:
    dataset_paths = (
        dataset.asset.path
        for dataset in channel.datasets
        if dataset.kind == "cross_section" and dataset.asset is not None
    )
    if any(_asset_is_available(path, asset_exists) for path in dataset_paths):
        return True
    cross_section = legacy_cross_section(channel)
    return cross_section is not None and _asset_is_available(
        cross_section.get("path"),
        asset_exists,
    )


def _status_allowed(channel: ReactionChannel, config: CaseConfig) -> bool:
    if channel.status in config.data_policy.allowed_status:
        return True
    if channel.status != "inferred":
        return False
    if not config.inference.enabled or not config.inference.include_inferred_reactions:
        return False
    score = confidence_score(channel)
    return score is not None and score >= config.inference.min_confidence


def _pair_data_allowed(
    channel: ReactionChannel,
    pair: CollisionPair,
    config: CaseConfig,
    *,
    species: Mapping[str, Species] | None,
    asset_exists: Callable[[str | None], bool] | None,
) -> bool:
    if pair.family == "electron":
        return (
            config.data_policy.include_reactions_without_cross_section
            or has_available_cross_section(channel, asset_exists)
        )
    if pair.family == "ion_neutral":
        return (
            config.data_policy.include_reactions_without_dnt_ready_properties
            or _has_dnt_ready_pair_properties(pair, species)
        )
    return True


def _asset_is_available(
    path: object,
    asset_exists: Callable[[str | None], bool] | None,
) -> bool:
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
