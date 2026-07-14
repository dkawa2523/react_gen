"""Convert one validated registry channel into a generated reaction."""

from __future__ import annotations

from plasma_reactgen.application.channel_compat import legacy_cross_section
from plasma_reactgen.application.channel_policy import has_available_cross_section
from plasma_reactgen.application.reaction_catalog import AssetExists
from plasma_reactgen.domain.equations import format_equation
from plasma_reactgen.domain.models import (
    CollisionPair,
    GeneratedReaction,
    ReactionChannel,
    SpeciesAmount,
)


def build_generated_reaction(
    *,
    channel: ReactionChannel,
    pair: CollisionPair,
    depth: int,
    reactants: list[SpeciesAmount],
    introduced_species: list[str],
    validation: dict[str, str],
    asset_exists: AssetExists | None = None,
) -> GeneratedReaction:
    return GeneratedReaction(
        id=channel.id,
        depth=depth,
        family=pair.family,
        type=channel.type,
        equation=format_equation(reactants=reactants, products=channel.products),
        reactants=reactants,
        products=channel.products,
        source_pair_key=pair.key,
        source_pair_label=pair.label,
        introduced_species=introduced_species,
        validation=validation,
        data_status=reaction_data_status(channel, pair.family, asset_exists),
        threshold_eV=channel.threshold_eV,
        deltaE_products_minus_reactants_eV=channel.deltaE_products_minus_reactants_eV,
        dnt_class=channel.dnt_class,
        data=channel.data,
        evidence=channel.evidence,
        provenance=channel.provenance,
        source_record=channel.source_record,
        confidence=channel.confidence,
        datasets=list(channel.datasets),
    )


def reaction_data_status(
    channel: ReactionChannel,
    family: str,
    asset_exists: AssetExists | None = None,
) -> dict[str, str]:
    """Summarize compatibility data status without hiding normalized datasets."""

    status = {"reaction": channel.status}
    if family == "electron":
        legacy = legacy_cross_section(channel)
        datasets = [item for item in channel.datasets if item.kind == "cross_section"]
        if not legacy and not datasets:
            status["cross_section"] = "missing"
        elif has_available_cross_section(channel, asset_exists):
            status["cross_section"] = "local_file_registered"
        elif (isinstance(legacy, dict) and legacy.get("path")) or any(
            item.asset and item.asset.path for item in datasets
        ):
            status["cross_section"] = "path_registered_but_missing"
        else:
            status["cross_section"] = (
                legacy.get("status", "reference_only_needs_import")
                if isinstance(legacy, dict)
                else "reference_only_needs_import"
            )
    elif family == "ion_neutral":
        status["dnt_class"] = "inferred" if channel.status == "inferred" else "registered"
    return status
