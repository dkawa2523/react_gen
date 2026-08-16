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
        pairs.extend(_electron_pairs(active_species, frontier_species_ids, config))
    if config.collisions.ion_neutral.enabled:
        pairs.extend(_ion_neutral_pairs(active_species, frontier_species_ids, config))
    unique_pairs = {pair.key: pair for pair in pairs}
    return [unique_pairs[key] for key in sorted(unique_pairs)]


def _electron_pairs(
    active_species: dict[str, Species],
    frontier_species_ids: set[str],
    config: CaseConfig,
) -> list[CollisionPair]:
    pairs = []
    for species_id in sorted(frontier_species_ids - {"e"}):
        species = active_species.get(species_id)
        if species and species_has_any_class(
            species,
            config.collisions.electron.targets,
        ):
            pairs.append(CollisionPair("electron", "e", species_id))
    return pairs


def _ion_neutral_pairs(
    active_species: dict[str, Species],
    frontier_species_ids: set[str],
    config: CaseConfig,
) -> list[CollisionPair]:
    ions = _species_with_classes(
        active_species,
        config.collisions.ion_neutral.projectiles,
    )
    neutrals = _species_with_classes(
        active_species,
        config.collisions.ion_neutral.targets,
    )
    return [
        CollisionPair("ion_neutral", ion, neutral)
        for ion in ions
        for neutral in neutrals
        if ion != neutral and (ion in frontier_species_ids or neutral in frontier_species_ids)
    ]


def _species_with_classes(
    species: dict[str, Species],
    classes: list[str],
) -> list[str]:
    return sorted(
        species_id
        for species_id, item in species.items()
        if species_id != "e" and species_has_any_class(item, classes)
    )
