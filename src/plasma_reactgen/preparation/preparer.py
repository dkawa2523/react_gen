"""Public orchestration for building a prepared registry workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.application.config import CaseConfig, load_case_config
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.preparation.preparation_context import (
    PreparationContext,
    build_preparation_context,
    record_context_sources,
    resolve_source_profile,
)
from plasma_reactgen.preparation.preparation_report import (
    PropertyEnrichmentState,
    initial_report,
    merge_property_enrichment,
    merge_reaction_report,
    seeded_species_ids,
)
from plasma_reactgen.preparation.prepared_species import (
    remove_unmodified_local_overlays,
    seed_species,
    write_prepared_species,
    write_yaml,
)
from plasma_reactgen.preparation.property_enrichment import enrich_species_properties
from plasma_reactgen.preparation.reaction_enrichment import enrich_reaction_channels


def prepare_case(
    input_path: str | Path,
    registry_root: str | Path,
    source_profile: str | dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    preserve_local_overlays: bool = False,
) -> dict[str, Any]:
    input_path = Path(input_path)
    registry_root = Path(registry_root)
    output_dir = (
        Path(output_dir) if output_dir is not None else input_path.parent / "prepared_registry"
    )
    config = load_case_config(input_path, registry_root)
    profile = resolve_source_profile(source_profile, registry_root)
    context = build_preparation_context(profile)
    report = initial_report(profile, output_dir, context)
    record_context_sources(report, output_dir.parent / "source_cache", context)
    if not context.has_providers:
        write_yaml(output_dir / "prepare_report.yaml", report)
        return report

    prepared_species = seed_species(
        config.gases,
        FileRegistry(registry_root),
        context.species_providers,
        report,
    )
    write_prepared_species(
        output_dir,
        prepared_species,
        has_property_providers=bool(context.property_providers),
    )
    property_state = _enrich_initial_properties(
        output_dir,
        profile,
        sorted({*config.gases, *prepared_species}),
        context,
        report,
    )
    if not preserve_local_overlays:
        remove_unmodified_local_overlays(output_dir)
    _enrich_reactions(
        output_dir,
        config,
        profile,
        context,
        property_state,
        report,
    )
    write_yaml(output_dir / "prepare_report.yaml", report)
    return report


def _enrich_initial_properties(
    output_dir: Path,
    profile: dict[str, Any],
    species_ids: list[str],
    context: PreparationContext,
    report: dict[str, Any],
) -> PropertyEnrichmentState:
    enrichment = enrich_species_properties(
        output_dir,
        context.property_providers,
        profile,
        species_ids=species_ids,
    )
    state, _ = merge_property_enrichment(report, enrichment)
    return state


def _enrich_reactions(
    output_dir: Path,
    config: CaseConfig,
    profile: dict[str, Any],
    context: PreparationContext,
    property_state: PropertyEnrichmentState,
    report: dict[str, Any],
) -> None:
    if not context.reaction_providers:
        return
    reaction_report = enrich_reaction_channels(
        output_dir,
        context.reaction_providers,
        config,
        profile,
        species_providers=context.species_providers,
    )
    seeded_properties = _enrich_seeded_properties(
        output_dir,
        profile,
        context,
        seeded_species_ids(reaction_report),
        property_state,
        report,
    )
    merge_reaction_report(report, reaction_report, seeded_properties)


def _enrich_seeded_properties(
    output_dir: Path,
    profile: dict[str, Any],
    context: PreparationContext,
    seeded_ids: list[str],
    property_state: PropertyEnrichmentState,
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    if not seeded_ids or not context.property_providers:
        return []
    enrichment = enrich_species_properties(
        output_dir,
        context.property_providers,
        profile,
        species_ids=seeded_ids,
    )
    _, newly_filled = merge_property_enrichment(report, enrichment, property_state)
    return newly_filled


__all__ = ["prepare_case"]
