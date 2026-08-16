from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.models import ReactionChannel


def passes_hard_filters(candidate: Any, context: Any = None) -> bool:
    """Placeholder for inference hard filters.

    Future screening should reuse the existing reaction validators for species
    reference, charge balance, and element balance instead of duplicating that
    chemistry logic here.
    """

    context = context or {}
    max_products = context.get("max_products") if isinstance(context, dict) else None
    if max_products is not None and len(_candidate_products(candidate)) > int(max_products):
        return False
    return True


def _candidate_products(candidate: Any) -> list:
    if isinstance(candidate, ReactionChannel):
        return list(candidate.products)
    if isinstance(candidate, dict):
        products = candidate.get("products", [])
        return list(products) if isinstance(products, list) else []
    return []
