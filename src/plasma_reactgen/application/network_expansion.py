"""Expand registered collision pairs into a reaction network.

This module owns the mutable expansion algorithm.  The public builder in
``network_builder`` only supplies repositories and keeps the stable API.
"""

from __future__ import annotations

from collections.abc import Callable

from plasma_reactgen.application.channel_policy import (
    is_channel_allowed,
    is_reaction_validation_allowed,
)
from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.network_expansion_state import (
    ExpansionState,
    apply_pair_limit,
    record_missing_pair,
    record_reaction_limit,
    record_species_truncation,
)
from plasma_reactgen.application.network_species_expansion import (
    load_registered_product_species,
    new_product_species_ids,
    register_product_nodes,
)
from plasma_reactgen.application.network_state import initialize_species
from plasma_reactgen.application.ports import ReactionRepository, RuleRepository, SpeciesRepository
from plasma_reactgen.application.reaction_factory import build_generated_reaction
from plasma_reactgen.domain.models import (
    CollisionPair,
    CoverageItem,
    MissingDataItem,
    ReactionChannel,
    ReactionNetwork,
    SpeciesAmount,
)
from plasma_reactgen.validation.validators import validate_reaction

AssetExists = Callable[[str | None], bool]

__all__ = ["expand_reaction_network"]


def expand_reaction_network(
    config: CaseConfig,
    reaction_repo: ReactionRepository,
    species_repo: SpeciesRepository,
    rule_repo: RuleRepository,
) -> ReactionNetwork:
    """Build one network while preserving all configured reporting limits."""

    _validate_species_limit(config)
    known, active, nodes = initialize_species(config.gases, species_repo)
    state = ExpansionState(known, active, nodes)
    reaction_catalog = rule_repo.get_reaction_type_catalog()
    asset_exists = _find_asset_exists(reaction_repo, species_repo, rule_repo)
    frontier = set(config.gases)

    for depth in range(config.expansion.max_depth + 1):
        frontier, stopped = _expand_depth(
            depth,
            frontier,
            state,
            config,
            reaction_repo,
            species_repo,
            reaction_catalog,
            asset_exists,
        )
        if stopped or not frontier:
            break

    return state.finish()


def _validate_species_limit(config: CaseConfig) -> None:
    input_species_count = len(set(config.gases))
    if input_species_count > config.limits.max_species:
        raise ValueError(
            "limits.max_species must accommodate all unique input gases "
            f"({config.limits.max_species} < {input_species_count})"
        )


def _expand_depth(
    depth: int,
    frontier: set[str],
    state: ExpansionState,
    config: CaseConfig,
    reaction_repo: ReactionRepository,
    species_repo: SpeciesRepository,
    reaction_catalog: dict,
    asset_exists: AssetExists | None,
) -> tuple[set[str], bool]:
    pairs = reaction_repo.find_pairs_involving(set(state.active_species), frontier)
    pairs = apply_pair_limit(pairs, depth, config, state)
    new_frontier: set[str] = set()
    missing_pairs = 0

    for pair in pairs:
        if pair.key in state.seen_pair_keys:
            continue
        state.seen_pair_keys.add(pair.key)
        channels = reaction_repo.get_channels(pair)
        if not channels:
            missing_pairs += 1
            record_missing_pair(pair, depth, missing_pairs, config, state)
            continue
        if _process_pair(
            pair,
            channels,
            depth,
            new_frontier,
            state,
            config,
            species_repo,
            reaction_catalog,
            asset_exists,
        ):
            return new_frontier, True

    return new_frontier, False


def _process_pair(
    pair: CollisionPair,
    channels: list[ReactionChannel],
    depth: int,
    new_frontier: set[str],
    state: ExpansionState,
    config: CaseConfig,
    species_repo: SpeciesRepository,
    reaction_catalog: dict,
    asset_exists: AssetExists | None,
) -> bool:
    eligible = _eligible_channels(channels, pair, state, config, asset_exists)
    if not eligible:
        state.coverage.append(
            CoverageItem(
                pair_key=pair.key,
                pair_label=pair.label,
                family=pair.family,
                depth=depth,
                status="filtered",
                reason="Registered channels did not pass the data policy",
                n_channels=0,
            )
        )
        return False

    state.coverage.append(
        CoverageItem(
            pair_key=pair.key,
            pair_label=pair.label,
            family=pair.family,
            depth=depth,
            status="found",
            n_channels=len(eligible),
        )
    )
    reactants = [SpeciesAmount(pair.projectile, 1.0), SpeciesAmount(pair.target, 1.0)]
    return any(
        _process_channel(
            channel,
            pair,
            reactants,
            depth,
            new_frontier,
            state,
            config,
            species_repo,
            reaction_catalog,
            asset_exists,
        )
        for channel in eligible
    )


def _eligible_channels(
    channels: list[ReactionChannel],
    pair: CollisionPair,
    state: ExpansionState,
    config: CaseConfig,
    asset_exists: AssetExists | None,
) -> list[ReactionChannel]:
    return [
        channel
        for channel in channels
        if is_channel_allowed(
            channel,
            config,
            pair=pair,
            species=state.known_species,
            asset_exists=asset_exists,
        )
        and channel.id not in state.seen_reaction_ids
    ]


def _process_channel(
    channel: ReactionChannel,
    pair: CollisionPair,
    reactants: list[SpeciesAmount],
    depth: int,
    new_frontier: set[str],
    state: ExpansionState,
    config: CaseConfig,
    species_repo: SpeciesRepository,
    reaction_catalog: dict,
    asset_exists: AssetExists | None,
) -> bool:
    load_registered_product_species(channel, species_repo, state)
    validation = validate_reaction(
        reactants=reactants,
        products=channel.products,
        species=state.known_species,
    )
    if _has_balance_failure(validation):
        state.missing_data.append(
            MissingDataItem(
                subject_kind="reaction",
                subject_id=channel.id,
                field="validation",
                required_by="network_builder",
                severity="error",
                message="Reaction rejected because charge or element balance failed.",
            )
        )
        return False
    if not is_reaction_validation_allowed(validation, config):
        return False
    if len(state.reactions) >= config.limits.max_reactions:
        record_reaction_limit(channel.id, depth, config, state)
        return True

    introduced = _expand_channel_species(
        channel,
        pair,
        depth,
        new_frontier,
        state,
        config,
        reaction_catalog,
    )
    if introduced is None:
        state.seen_reaction_ids.add(channel.id)
        return False

    state.reactions.append(
        build_generated_reaction(
            channel=channel,
            pair=pair,
            depth=depth,
            reactants=reactants,
            introduced_species=introduced,
            validation=validation,
            asset_exists=asset_exists,
        )
    )
    state.seen_reaction_ids.add(channel.id)
    return False


def _has_balance_failure(validation: dict[str, str]) -> bool:
    return validation["charge_balance"] == "failed" or validation["element_balance"] == "failed"


def _expand_channel_species(
    channel: ReactionChannel,
    pair: CollisionPair,
    depth: int,
    new_frontier: set[str],
    state: ExpansionState,
    config: CaseConfig,
    reaction_catalog: dict,
) -> list[str] | None:
    channel_rule = reaction_catalog.get(pair.family, {}).get(channel.type, {})
    if not bool(channel_rule.get("expands_species", True)):
        return []
    new_species = new_product_species_ids(channel.products, state)
    if len(state.species_nodes) + len(new_species) > config.limits.max_species:
        record_species_truncation(channel.id, new_species, depth, config, state)
        return None
    return register_product_nodes(channel, depth, new_frontier, state, config)


def _find_asset_exists(*repositories: object) -> AssetExists | None:
    for repository in repositories:
        predicate = getattr(repository, "asset_exists", None)
        if callable(predicate):
            return predicate
    return None
