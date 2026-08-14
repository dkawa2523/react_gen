"""Prepare-report construction and incremental enrichment bookkeeping."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plasma_reactgen.preparation.preparation_context import PreparationContext


@dataclass
class PropertyEnrichmentState:
    properties_filled: list[dict[str, Any]] = field(default_factory=list)
    property_conflicts: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    def extend(self, enrichment: dict[str, Any]) -> list[dict[str, Any]]:
        filled = list(enrichment["properties_filled"])
        self.properties_filled.extend(filled)
        self.property_conflicts.extend(enrichment["property_conflicts"])
        self.unresolved.extend(enrichment["unresolved"])
        return filled


def initial_report(
    profile: dict[str, Any],
    output_dir: Path,
    context: PreparationContext,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "source_profile": {
            "name": profile.get("name", "custom"),
            "internal_file_root": _optional_path(context.internal_root),
            "nist_snapshot_root": _optional_path(context.nist_root),
            "ion_reaction_table_files": [str(path) for path in context.ion_reaction_table_files],
            "chemicals_optional": context.uses_chemicals,
        },
        "prepared_registry": str(output_dir),
        "summary": {
            "n_species_written": 0,
            "n_properties_filled": 0,
            "n_reaction_pairs_imported": 0,
            "n_species_seeded_from_reactions": 0,
            "n_properties_filled_for_seeded_species": 0,
            "n_unresolved_product_species": 0,
        },
        "entries": [],
        "source_cache": [],
        "source_provider_warnings": context.provider_warnings,
        "unavailable_sources": context.unavailable_sources,
        "species_seeded_from_reactions": [],
        "properties_filled_for_seeded_species": [],
        "unresolved_product_species": [],
    }


def merge_property_enrichment(
    report: dict[str, Any],
    enrichment: dict[str, Any],
    state: PropertyEnrichmentState | None = None,
) -> tuple[PropertyEnrichmentState, list[dict[str, Any]]]:
    state = state or PropertyEnrichmentState()
    newly_filled = state.extend(enrichment)
    report["properties_filled"] = state.properties_filled
    report["property_conflicts"] = state.property_conflicts
    report["unresolved"] = state.unresolved
    report["summary"].update(
        {
            "n_properties_filled": len(state.properties_filled),
            "n_property_conflicts": len(state.property_conflicts),
            "n_unresolved_properties": len(state.unresolved),
        }
    )
    return state, newly_filled


def seeded_species_ids(reaction_report: dict[str, Any]) -> list[str]:
    return sorted(
        {
            item["species"]
            for item in reaction_report.get("species_seeded_from_reactions", [])
            if item.get("species")
        }
    )


def merge_reaction_report(
    report: dict[str, Any],
    reaction_report: dict[str, Any],
    seeded_properties: list[dict[str, Any]],
) -> None:
    for key in (
        "species_seeded_from_reactions",
        "unresolved_product_species",
        "reaction_pairs_imported",
        "reaction_channels_imported",
        "reaction_channels_skipped",
        "unresolved_reactions",
    ):
        report[key] = reaction_report[key]
    report["properties_filled_for_seeded_species"] = seeded_properties
    summary = reaction_report["summary"]
    report["summary"].update(
        {
            "n_reaction_pairs_imported": summary["n_reaction_pairs_imported"],
            "n_reaction_channels_imported": summary["n_reaction_channels_imported"],
            "n_reaction_channels_skipped": summary["n_reaction_channels_skipped"],
            "n_species_seeded_from_reactions": summary["n_species_seeded_from_reactions"],
            "n_properties_filled_for_seeded_species": len(seeded_properties),
            "n_unresolved_product_species": summary["n_unresolved_product_species"],
            "n_unresolved_reactions": summary["n_unresolved_reactions"],
        }
    )


def _optional_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None


__all__ = [
    "PropertyEnrichmentState",
    "initial_report",
    "merge_property_enrichment",
    "merge_reaction_report",
    "seeded_species_ids",
]
