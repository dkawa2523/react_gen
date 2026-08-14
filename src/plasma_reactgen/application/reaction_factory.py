"""Convert one validated registry channel into a generated reaction."""

from __future__ import annotations

from plasma_reactgen.application.reaction_catalog import AssetExists
from plasma_reactgen.application.reaction_data_status import reaction_data_status
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


__all__ = ["build_generated_reaction", "reaction_data_status"]
