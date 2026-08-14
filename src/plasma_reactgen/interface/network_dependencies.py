from __future__ import annotations

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies
from plasma_reactgen.inference.provider import (
    CompositeReactionProvider,
    InferredReactionProvider,
    RegisteredReactionProvider,
)
from plasma_reactgen.infrastructure.file_registry import FileRegistry


def build_network_dependencies(
    registry: FileRegistry,
    config: CaseConfig,
) -> NetworkBuilderDependencies:
    if not (config.inference.enabled and config.inference.include_inferred_reactions):
        return NetworkBuilderDependencies(
            species_repo=registry,
            reaction_repo=registry,
            rule_repo=registry,
        )

    composite = CompositeReactionProvider(
        registered=RegisteredReactionProvider(registry),
        inferred=InferredReactionProvider(species_repo=registry),
        config=config,
    )
    return NetworkBuilderDependencies(
        species_repo=composite,
        reaction_repo=composite,
        rule_repo=registry,
    )
