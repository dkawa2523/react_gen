from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.models import CollisionPair, ReactionChannel, Species, SpeciesAmount
from plasma_reactgen.inference.provider import CompositeReactionProvider


def build_reaction_candidates(
    species: list[Species],
    provider: CompositeReactionProvider,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    neutral_species = [item for item in species if item.charge == 0]

    electron_channels = []
    for target in neutral_species:
        electron_channels.extend(
            _append_pair_candidates(
                candidates,
                seen_ids,
                provider,
                CollisionPair("electron", "e", target.id),
            )
        )

    for projectile in _ion_projectiles(electron_channels):
        for target in neutral_species:
            if projectile != target.id:
                _append_pair_candidates(
                    candidates,
                    seen_ids,
                    provider,
                    CollisionPair("ion_neutral", projectile, target.id),
                )
    return candidates


def _append_pair_candidates(
    candidates: list[dict[str, Any]],
    seen_ids: set[str],
    provider: CompositeReactionProvider,
    pair: CollisionPair,
) -> list[ReactionChannel]:
    added = []
    for channel in provider.get_channels(pair):
        if channel.status != "inferred" or channel.id in seen_ids:
            continue
        seen_ids.add(channel.id)
        candidates.append(_reaction_candidate_payload(pair, channel))
        added.append(channel)
    return added


def _ion_projectiles(channels: list[ReactionChannel]) -> list[str]:
    return sorted(
        {
            channel.products[1].species
            for channel in channels
            if channel.type == "ionization" and len(channel.products) > 1
        }
    )


def _reaction_candidate_payload(
    pair: CollisionPair,
    channel: ReactionChannel,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "reaction_channel_candidate",
        "id": channel.id,
        "status": channel.status,
        "pair": {
            "family": pair.family,
            "projectile": pair.projectile,
            "target": pair.target,
        },
        "type": channel.type,
        "products": [_amount_payload(amount) for amount in channel.products],
        "threshold_eV": channel.threshold_eV,
        "deltaE_products_minus_reactants_eV": channel.deltaE_products_minus_reactants_eV,
        "dnt_class": channel.dnt_class,
        "data": channel.data,
    }


def _amount_payload(amount: SpeciesAmount) -> dict[str, Any]:
    return {"species": amount.species, "n": amount.n}
