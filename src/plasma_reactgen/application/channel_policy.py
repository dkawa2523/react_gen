from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.channel_compat import confidence_score, legacy_cross_section
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
        score = confidence_score(channel)
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


def has_available_cross_section(
    channel: ReactionChannel,
    asset_exists: Callable[[str | None], bool] | None,
) -> bool:
    if asset_exists is not None:
        for dataset in channel.datasets:
            if (
                dataset.kind == "cross_section"
                and dataset.asset is not None
                and dataset.asset.path
            ):
                try:
                    if bool(asset_exists(dataset.asset.path)):
                        return True
                except (OSError, TypeError, ValueError):
                    continue

    cross_section = legacy_cross_section(channel)
    if cross_section is None:
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
