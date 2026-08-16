"""Public entry point for reaction-network construction."""

from __future__ import annotations

from dataclasses import dataclass

from plasma_reactgen.application import network_expansion
from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.ports import ReactionRepository, RuleRepository, SpeciesRepository
from plasma_reactgen.domain.models import ReactionNetwork


@dataclass
class NetworkBuilderDependencies:
    reaction_repo: ReactionRepository
    species_repo: SpeciesRepository
    rule_repo: RuleRepository


class ReactionNetworkBuilder:
    """Build reaction networks from repositories.

    Missing scientific data remains diagnostic output; malformed registered
    reactions are rejected by the expansion engine.
    """

    def __init__(self, deps: NetworkBuilderDependencies):
        self.deps = deps

    def generate(self, config: CaseConfig) -> ReactionNetwork:
        return network_expansion.expand_reaction_network(
            config,
            self.deps.reaction_repo,
            self.deps.species_repo,
            self.deps.rule_repo,
        )
