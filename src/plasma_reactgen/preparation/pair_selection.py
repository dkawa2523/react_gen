from __future__ import annotations

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.chemistry import species_has_any_class
from plasma_reactgen.domain.models import CollisionPair, Species


def select_pairs_involving_frontier(
    active_species: dict[str, Species],
    frontier_species_ids: set[str],
    config: CaseConfig,
) -> list[CollisionPair]:
    """Legacy family-specific selection used only by preparation workflows."""

    pairs: list[CollisionPair] = []
    if config.collisions.electron.enabled:
        for species_id in sorted(frontier_species_ids):
            species = active_species.get(species_id)
            if species_id != "e" and species and species_has_any_class(
                species, config.collisions.electron.targets
            ):
                pairs.append(CollisionPair("electron", "e", species_id))

    if config.collisions.ion_neutral.enabled:
        ions = _species_with_classes(
            active_species, config.collisions.ion_neutral.projectiles
        )
        neutrals = _species_with_classes(
            active_species, config.collisions.ion_neutral.targets
        )
        for species_id in sorted(frontier_species_ids):
            if species_id in ions:
                pairs.extend(
                    CollisionPair("ion_neutral", species_id, neutral)
                    for neutral in neutrals
                    if neutral != species_id
                )
            if species_id in neutrals:
                pairs.extend(
                    CollisionPair("ion_neutral", ion, species_id)
                    for ion in ions
                    if ion != species_id
                )
    return [pair for _, pair in sorted({pair.key: pair for pair in pairs}.items())]


def _species_with_classes(
    species: dict[str, Species],
    classes: list[str],
) -> list[str]:
    return sorted(
        species_id
        for species_id, item in species.items()
        if species_id != "e" and species_has_any_class(item, classes)
    )
