from __future__ import annotations

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.chemistry import species_has_any_class
from plasma_reactgen.domain.models import CollisionPair, Species


def select_pairs_involving_frontier(
    active_species: dict[str, Species],
    frontier_species_ids: set[str],
    config: CaseConfig,
) -> list[CollisionPair]:
    pairs: list[CollisionPair] = []

    if config.collisions.electron.enabled:
        for sid in sorted(frontier_species_ids):
            if sid == "e" or sid not in active_species:
                continue
            sp = active_species[sid]
            if species_has_any_class(sp, config.collisions.electron.targets):
                pairs.append(CollisionPair(family="electron", projectile="e", target=sid))

    if config.collisions.ion_neutral.enabled:
        ions = [
            sid
            for sid, sp in active_species.items()
            if sid != "e" and species_has_any_class(sp, config.collisions.ion_neutral.projectiles)
        ]
        neutrals = [
            sid
            for sid, sp in active_species.items()
            if sid != "e" and species_has_any_class(sp, config.collisions.ion_neutral.targets)
        ]

        for sid in sorted(frontier_species_ids):
            if sid not in active_species or sid == "e":
                continue
            sp = active_species[sid]

            if species_has_any_class(sp, config.collisions.ion_neutral.projectiles):
                for neutral in sorted(neutrals):
                    if sid != neutral:
                        pairs.append(
                            CollisionPair(
                                family="ion_neutral",
                                projectile=sid,
                                target=neutral,
                            )
                        )

            if species_has_any_class(sp, config.collisions.ion_neutral.targets):
                for ion in sorted(ions):
                    if ion != sid:
                        pairs.append(
                            CollisionPair(
                                family="ion_neutral",
                                projectile=ion,
                                target=sid,
                            )
                        )

    return _unique_pairs(pairs)


def _unique_pairs(pairs: list[CollisionPair]) -> list[CollisionPair]:
    seen: set[str] = set()
    out: list[CollisionPair] = []
    for pair in pairs:
        if pair.key in seen:
            continue
        seen.add(pair.key)
        out.append(pair)
    return out
