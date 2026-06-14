from __future__ import annotations

from plasma_reactgen.application.dnt_input_builder import build_dnt_inputs
from plasma_reactgen.domain.models import ReactionNetwork


def build_dnt_pair_inputs(network: ReactionNetwork, dnt_tasks: list[dict] | None = None) -> list[dict]:
    """Compatibility wrapper for the normalized DNT input builder."""

    _ = dnt_tasks
    return list(build_dnt_inputs(network).get("pairs", []))
