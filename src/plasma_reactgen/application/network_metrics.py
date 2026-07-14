from __future__ import annotations

from plasma_reactgen.application.reaction_catalog import provenance_summary
from plasma_reactgen.domain.models import ReactionNetwork


def count_dnt_status(tasks: list[dict], field: str, status: str) -> int:
    """Count one readiness status, including the legacy readiness alias."""

    count = 0
    for task in tasks:
        readiness = task.get(field)
        if not isinstance(readiness, dict) and field == "pair_property_readiness":
            readiness = task.get("readiness")
        if isinstance(readiness, dict) and readiness.get("status") == status:
            count += 1
    return count


def has_cross_section_asset(data_status: dict) -> bool:
    return data_status.get("cross_section") == "local_file_registered"


def count_reactions_with_cross_section_asset(network: ReactionNetwork) -> int:
    return sum(
        has_cross_section_asset(reaction.data_status)
        for reaction in network.reactions
    )


def count_electron_reactions_missing_cross_section(network: ReactionNetwork) -> int:
    return sum(
        reaction.family == "electron"
        and not has_cross_section_asset(reaction.data_status)
        for reaction in network.reactions
    )


def count_reactions_with_provenance(network: ReactionNetwork) -> int:
    return sum(
        provenance_summary(reaction)["available"]
        for reaction in network.reactions
    )
