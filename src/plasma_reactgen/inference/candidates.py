from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.models import ReactionNetwork


def propose_reaction_candidates(
    network: ReactionNetwork,
    *,
    enabled: bool = False,
    max_depth: int | None = None,
    max_products_per_channel: int | None = None,
) -> list[dict[str, Any]]:
    """Legacy compatibility helper for older candidate callers.

    Normal generation and ``infer-candidates`` use the provider/candidate-writer
    layer. This helper remains disconnected from ``ReactionNetworkBuilder`` and
    emits nothing unless a future caller deliberately extends it.
    """

    _ = (network, max_depth, max_products_per_channel)
    if not enabled:
        return []
    return []


def build_inferred_candidate(
    *,
    pair_key: str,
    reaction_type: str,
    reactants: list[dict[str, Any]],
    products: list[dict[str, Any]],
    confidence: float,
    method: str,
    reason: str,
    missing_for_complete_dnt: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
    max_depth: int | None = None,
    max_products_per_channel: int | None = None,
) -> dict[str, Any]:
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")

    return {
        "kind": "legacy_reaction_candidate",
        "status": "inferred",
        "confidence": float(confidence),
        "pair_key": pair_key,
        "type": reaction_type,
        "reactants": reactants,
        "products": products,
        "inference": {
            "method": method,
            "reason": reason,
            "constraints": {
                "max_depth": max_depth,
                "max_products_per_channel": max_products_per_channel,
            },
        },
        "missing_for_complete_dnt": list(missing_for_complete_dnt or []),
        "provenance": provenance or {"source": "plasma_reactgen.inference"},
    }
