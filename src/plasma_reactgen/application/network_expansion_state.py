"""Mutable state and limit bookkeeping for reaction-network expansion."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.network_state import finalize_network
from plasma_reactgen.domain.models import (
    CollisionPair,
    CoverageItem,
    GeneratedReaction,
    MissingDataItem,
    NetworkSpeciesNode,
    ReactionNetwork,
    Species,
    TruncationEvent,
)


@dataclass
class ExpansionState:
    """Values accumulated while walking the reaction frontier."""

    known_species: dict[str, Species]
    active_species: dict[str, Species]
    species_nodes: dict[str, NetworkSpeciesNode]
    reactions: list[GeneratedReaction] = field(default_factory=list)
    coverage: list[CoverageItem] = field(default_factory=list)
    missing_data: list[MissingDataItem] = field(default_factory=list)
    truncations: list[TruncationEvent] = field(default_factory=list)
    seen_reaction_ids: set[str] = field(default_factory=set)
    seen_pair_keys: set[str] = field(default_factory=set)

    def finish(self) -> ReactionNetwork:
        return finalize_network(
            species=self.known_species,
            species_nodes=self.species_nodes,
            reactions=self.reactions,
            coverage=self.coverage,
            missing_data=self.missing_data,
            truncations=self.truncations,
        )


def apply_pair_limit(
    pairs: list[CollisionPair],
    depth: int,
    config: CaseConfig,
    state: ExpansionState,
) -> list[CollisionPair]:
    limit = config.limits.max_pairs_per_depth
    if len(pairs) <= limit:
        return pairs
    state.truncations.append(
        TruncationEvent(
            limit_name="max_pairs_per_depth",
            scope="pair_selection",
            limit_value=limit,
            depth=depth,
            observed_count=len(pairs),
            retained_count=limit,
            omitted_count=len(pairs) - limit,
        )
    )
    return pairs[:limit]


def record_missing_pair(
    pair: CollisionPair,
    depth: int,
    observed_count: int,
    config: CaseConfig,
    state: ExpansionState,
) -> None:
    limit = config.limits.max_missing_pairs_per_depth
    if observed_count <= limit:
        state.coverage.append(
            CoverageItem(
                pair_key=pair.key,
                pair_label=pair.label,
                family=pair.family,
                depth=depth,
                status="missing",
                reason="No registered reaction file",
                n_channels=0,
            )
        )
    _record_missing_report_truncation(state.truncations, depth, observed_count, limit)


def record_reaction_limit(
    channel_id: str,
    depth: int,
    config: CaseConfig,
    state: ExpansionState,
) -> None:
    state.truncations.append(
        TruncationEvent(
            limit_name="max_reactions",
            scope="reactions",
            limit_value=config.limits.max_reactions,
            depth=depth,
            observed_count=len(state.reactions) + 1,
            retained_count=len(state.reactions),
            omitted_count=None,
            details={"first_omitted_reaction_id": channel_id},
        )
    )


def record_species_truncation(
    channel_id: str,
    blocked_species_ids: list[str],
    depth: int,
    config: CaseConfig,
    state: ExpansionState,
) -> None:
    retained_count = len(state.species_nodes)
    state.truncations.append(
        TruncationEvent(
            limit_name="max_species",
            scope="species_expansion",
            limit_value=config.limits.max_species,
            depth=depth,
            observed_count=retained_count + len(blocked_species_ids),
            retained_count=retained_count,
            omitted_count=len(blocked_species_ids),
            details={
                "blocked_reaction_ids": [channel_id],
                "blocked_species_ids": list(blocked_species_ids),
            },
        )
    )


def _record_missing_report_truncation(
    truncations: list[TruncationEvent],
    depth: int,
    observed_count: int,
    limit: int,
) -> None:
    if observed_count <= limit:
        return
    existing = next(
        (
            event
            for event in truncations
            if event.limit_name == "max_missing_pairs_per_depth" and event.depth == depth
        ),
        None,
    )
    if existing is None:
        truncations.append(
            TruncationEvent(
                limit_name="max_missing_pairs_per_depth",
                scope="coverage.missing_pairs",
                limit_value=limit,
                depth=depth,
                observed_count=observed_count,
                retained_count=limit,
                omitted_count=observed_count - limit,
            )
        )
        return
    index = truncations.index(existing)
    truncations[index] = replace(
        existing,
        observed_count=observed_count,
        omitted_count=observed_count - limit,
    )
