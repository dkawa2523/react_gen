from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species


class RegisteredReactionProvider:
    """Expose registry reactions through the network provider interface."""

    def __init__(self, repository: Any):
        self.repository = repository

    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        return self.repository.get_channels(pair)

    def find_pairs_involving(
        self,
        active_species_ids: set[str],
        frontier_species_ids: set[str],
    ) -> list[CollisionPair]:
        return self.repository.find_pairs_involving(
            active_species_ids,
            frontier_species_ids,
        )

    def has_pair(self, pair: CollisionPair) -> bool:
        return self.repository.has_pair(pair)

    def get_species(self, species_id: str) -> Species | None:
        if hasattr(self.repository, "get_species"):
            return self.repository.get_species(species_id)
        return None

    def has_species(self, species_id: str) -> bool:
        if hasattr(self.repository, "has_species"):
            return bool(self.repository.has_species(species_id))
        return self.get_species(species_id) is not None


__all__ = ["RegisteredReactionProvider"]
