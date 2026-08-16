from __future__ import annotations

from collections.abc import Callable

from plasma_reactgen.application.channel_compat import confidence_score
from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species
from plasma_reactgen.inference.inferred_provider import (
    InferredReactionProvider,
    inference_enabled,
)
from plasma_reactgen.inference.registered_provider import RegisteredReactionProvider
from plasma_reactgen.inference.screening import passes_hard_filters


class CompositeReactionProvider:
    """Combine curated and inferred data while giving curated data priority."""

    def __init__(
        self,
        registered: RegisteredReactionProvider,
        inferred: InferredReactionProvider,
        config: CaseConfig,
    ):
        self.registered = registered
        self.inferred = inferred
        self.config = config

    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        registered_channels = self.registered.get_channels(pair)
        if not inference_enabled(self.config):
            return registered_channels

        seen_ids = {channel.id for channel in registered_channels}
        inferred_channels = [
            channel
            for channel in self.inferred.get_channels(pair, {"config": self.config})
            if channel.id not in seen_ids
            and (confidence_score(channel) or 0.0) >= self.config.inference.min_confidence
            and passes_hard_filters(
                channel,
                {"max_products": self.config.inference.max_products},
            )
        ]
        return [*registered_channels, *inferred_channels]

    def find_pairs_involving(
        self,
        active_species_ids: set[str],
        frontier_species_ids: set[str],
    ) -> list[CollisionPair]:
        registered_pairs = self.registered.find_pairs_involving(
            active_species_ids,
            frontier_species_ids,
        )
        if not inference_enabled(self.config):
            return registered_pairs

        candidates = [*registered_pairs, *_electron_pairs(frontier_species_ids)]
        candidates.extend(
            _ion_neutral_pairs(
                active_species_ids,
                frontier_species_ids,
                get_species=self.get_species,
            )
        )
        return _unique_pairs(candidates)

    def has_pair(self, pair: CollisionPair) -> bool:
        return self.registered.has_pair(pair) or bool(self.get_channels(pair))

    def get_species(self, species_id: str) -> Species | None:
        return self.registered.get_species(species_id) or self.inferred.get_species(species_id)

    def has_species(self, species_id: str) -> bool:
        return self.get_species(species_id) is not None


def _electron_pairs(frontier_species_ids: set[str]) -> list[CollisionPair]:
    return [
        CollisionPair("electron", "e", species_id)
        for species_id in sorted(frontier_species_ids)
        if species_id != "e"
    ]


def _ion_neutral_pairs(
    active_species_ids: set[str],
    frontier_species_ids: set[str],
    *,
    get_species: Callable[[str], Species | None],
) -> list[CollisionPair]:
    ions: list[str] = []
    neutrals: list[str] = []
    for species_id in sorted(active_species_ids - {"e"}):
        species = get_species(species_id)
        if species is None:
            continue
        (ions if species.charge > 0 else neutrals).append(species_id)
    return [
        CollisionPair("ion_neutral", ion, neutral)
        for ion in ions
        for neutral in neutrals
        if ion in frontier_species_ids or neutral in frontier_species_ids
    ]


def _unique_pairs(pairs: list[CollisionPair]) -> list[CollisionPair]:
    return [pair for _, pair in sorted({pair.key: pair for pair in pairs}.items())]


__all__ = ["CompositeReactionProvider"]
