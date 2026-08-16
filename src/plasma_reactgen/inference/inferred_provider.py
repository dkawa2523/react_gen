from __future__ import annotations

from typing import Any

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species
from plasma_reactgen.inference.inferred_species import (
    neutral_counterpart_id,
    neutral_from_ion,
    species_from_candidate,
)
from plasma_reactgen.inference.reaction_templates import (
    electron_parent_ionization_channel,
    ion_neutral_parent_charge_transfer_channel,
)
from plasma_reactgen.inference.species_candidates import make_parent_ion_candidates


class InferredReactionProvider:
    """Generate conservative in-memory reaction channels when enabled.

    Generated species stay in memory; curated registry files are never mutated.
    """

    def __init__(self, species_repo: Any | None = None):
        self.species_repo = species_repo
        self._species_cache: dict[str, Species] = {}

    def get_channels(
        self,
        pair: CollisionPair,
        context: Any = None,
    ) -> list[ReactionChannel]:
        config = context_config(context)
        if config is None or not inference_enabled(config):
            return []
        if pair.family == "electron":
            return self._electron_parent_ionization(pair, config)
        if pair.family == "ion_neutral":
            return self._ion_neutral_parent_charge_transfer(pair, config)
        return []

    def get_species(self, species_id: str) -> Species | None:
        return self._species_cache.get(species_id)

    def has_species(self, species_id: str) -> bool:
        return species_id in self._species_cache

    def _electron_parent_ionization(
        self,
        pair: CollisionPair,
        config: CaseConfig,
    ) -> list[ReactionChannel]:
        if pair.projectile != "e":
            return []
        target = self._get_species(pair.target)
        if target is None or target.charge != 0:
            return []
        product_ion = self._ensure_parent_cation(target, config)
        if product_ion is None:
            return []
        return [electron_parent_ionization_channel(target, product_ion)]

    def _ion_neutral_parent_charge_transfer(
        self,
        pair: CollisionPair,
        config: CaseConfig,
    ) -> list[ReactionChannel]:
        projectile = self._get_species(pair.projectile)
        target = self._get_species(pair.target)
        if projectile is None or target is None:
            return []
        if projectile.charge <= 0 or target.charge != 0:
            return []

        neutral_projectile = self._ensure_neutral_counterpart(projectile, config)
        target_cation = self._ensure_parent_cation(target, config)
        if neutral_projectile is None or target_cation is None:
            return []
        return [
            ion_neutral_parent_charge_transfer_channel(
                projectile,
                target,
                neutral_projectile,
                target_cation,
            )
        ]

    def _ensure_parent_cation(self, parent: Species, config: CaseConfig) -> str | None:
        species_id = f"{parent.id}+"
        if self._get_registered_species(species_id) is not None:
            return species_id
        if not config.inference.include_inferred_species:
            return None
        if species_id in self._species_cache:
            return species_id

        candidates = [
            candidate
            for candidate in make_parent_ion_candidates(parent)
            if candidate.get("charge") == 1
        ]
        if not candidates:
            return None
        self._species_cache[species_id] = species_from_candidate(
            candidates[0],
            species_id=species_id,
            parent=parent,
        )
        return species_id

    def _ensure_neutral_counterpart(
        self,
        ion: Species,
        config: CaseConfig,
    ) -> str | None:
        species_id = neutral_counterpart_id(ion.id)
        if self._get_registered_species(species_id) is not None:
            return species_id
        if not config.inference.include_inferred_species:
            return None
        if species_id not in self._species_cache:
            self._species_cache[species_id] = neutral_from_ion(ion, species_id)
        return species_id

    def _get_species(self, species_id: str) -> Species | None:
        return self._get_registered_species(species_id) or self._species_cache.get(species_id)

    def _get_registered_species(self, species_id: str) -> Species | None:
        if self.species_repo is None or not hasattr(self.species_repo, "get_species"):
            return None
        return self.species_repo.get_species(species_id)


def context_config(context: Any) -> CaseConfig | None:
    if isinstance(context, dict):
        config = context.get("config")
        return config if isinstance(config, CaseConfig) else None
    return context if isinstance(context, CaseConfig) else None


def inference_enabled(config: CaseConfig | None) -> bool:
    return bool(config and config.inference.enabled and config.inference.include_inferred_reactions)


__all__ = ["InferredReactionProvider", "inference_enabled"]
