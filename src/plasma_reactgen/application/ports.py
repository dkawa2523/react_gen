from __future__ import annotations

from typing import Protocol

from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species


class SpeciesRepository(Protocol):
    def get_species(self, species_id: str) -> Species | None:
        ...

    def has_species(self, species_id: str) -> bool:
        ...


class ReactionRepository(Protocol):
    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        ...

    def has_pair(self, pair: CollisionPair) -> bool:
        ...


class RuleRepository(Protocol):
    def get_reaction_type_catalog(self) -> dict:
        ...

    def get_role_required_properties(self) -> dict:
        ...
