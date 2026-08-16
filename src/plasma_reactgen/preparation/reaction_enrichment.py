"""Reaction-enrichment traversal and stable public API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import CollisionPair, Species
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.preparation.pair_selection import (
    select_pairs_involving_frontier,
)
from plasma_reactgen.preparation.reaction_enrichment_channels import (
    append_channels,
    existing_channel_ids,
    iter_provider_channels,
    normalize_channel,
    validate_channel,
)
from plasma_reactgen.preparation.reaction_enrichment_report import (
    ReactionEnrichmentReport,
)
from plasma_reactgen.preparation.reaction_enrichment_species import (
    collect_existing_channel_frontier,
    collect_new_frontier_species,
    load_active_species,
    persist_resolved_species,
    resolve_product_species,
)


@dataclass
class _EnrichmentContext:
    prepared_registry: Path
    registry: FileRegistry
    providers: list[Any]
    species_providers: list[Any]
    config: CaseConfig
    species: dict[str, Species]
    discovered_species: set[str]
    report: ReactionEnrichmentReport


def enrich_reaction_channels(
    prepared_registry: Path,
    providers: list[Any],
    config: CaseConfig,
    source_profile: dict[str, Any],
    species_providers: list[Any] | None = None,
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    registry = FileRegistry(prepared_registry)
    context = _EnrichmentContext(
        prepared_registry=prepared_registry,
        registry=registry,
        providers=providers,
        species_providers=species_providers or [],
        config=config,
        species=load_active_species(registry, config),
        discovered_species={"e", *config.gases},
        report=ReactionEnrichmentReport.create(source_profile),
    )
    frontier = set(config.gases)
    seen_pair_keys: set[str] = set()
    depth_limit = config.expansion.max_depth
    maximum_iterations = (
        depth_limit + 1 if depth_limit is not None else config.limits.max_species + 1
    )
    for _depth in range(maximum_iterations):
        frontier = _expand_depth(context, frontier, seen_pair_keys)
        if not frontier:
            break
    return context.report.finalize()


def _expand_depth(
    context: _EnrichmentContext,
    frontier: set[str],
    seen_pair_keys: set[str],
) -> set[str]:
    new_frontier: set[str] = set()
    pairs = select_pairs_involving_frontier(
        context.species,
        frontier,
        context.config,
    )
    for pair in pairs:
        if pair.key in seen_pair_keys:
            continue
        seen_pair_keys.add(pair.key)
        _enrich_pair(context, pair, new_frontier)
    return new_frontier


def _enrich_pair(
    context: _EnrichmentContext,
    pair: CollisionPair,
    new_frontier: set[str],
) -> None:
    collect_existing_channel_frontier(
        context.registry,
        pair,
        context.species,
        context.discovered_species,
        new_frontier,
        context.config,
    )
    channel_ids = existing_channel_ids(context.registry, pair)
    accepted = []
    for raw_channel in iter_provider_channels(context.providers, pair):
        channel = _prepare_channel(
            context,
            pair,
            raw_channel,
            channel_ids,
            new_frontier,
        )
        if channel is not None:
            accepted.append(channel)
    if accepted:
        append_channels(context.prepared_registry, pair, accepted)
        context.report.imported(pair, accepted)


def _prepare_channel(
    context: _EnrichmentContext,
    pair: CollisionPair,
    raw_channel: dict[str, Any],
    existing_ids: set[str],
    new_frontier: set[str],
) -> dict[str, Any] | None:
    channel = normalize_channel(raw_channel)
    channel_id = channel.get("id")
    if not channel_id:
        context.report.unresolved(pair, None, "missing_channel_id")
        return None
    if channel_id in existing_ids:
        context.report.skipped(pair, channel_id, "duplicate_channel")
        return None

    resolution = resolve_product_species(
        channel,
        context.species,
        context.registry,
        context.species_providers,
    )
    if resolution.unresolved:
        context.report.product_resolution_failed(
            pair,
            channel_id,
            resolution.unresolved,
        )
        return None

    validation = validate_channel(
        pair,
        channel,
        {**context.species, **resolution.species},
    )
    if validation["species_reference"] != "ok":
        context.report.unresolved(pair, channel_id, "missing_product_species")
        return None
    if validation["charge_balance"] != "ok" or validation["element_balance"] != "ok":
        context.report.skipped(
            pair,
            channel_id,
            "validation_failed",
            validation,
        )
        return None

    seeded = persist_resolved_species(
        context.prepared_registry,
        context.species,
        resolution,
        pair,
        channel_id,
    )
    context.report.add_seeded(seeded)
    collect_new_frontier_species(
        channel,
        context.species,
        context.discovered_species,
        new_frontier,
        context.config,
    )
    existing_ids.add(channel_id)
    return channel


__all__ = ["enrich_reaction_channels"]
