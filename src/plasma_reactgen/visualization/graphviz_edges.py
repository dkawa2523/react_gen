from __future__ import annotations

from typing import Any


def non_electron_species(amounts: Any) -> list[str]:
    if not isinstance(amounts, list):
        return []
    return [
        species_id
        for amount in amounts
        if isinstance(amount, dict)
        and (species_id := str(amount.get("species", "")))
        and species_id != "e"
    ]


def reaction_changes_species(reactants: list[str], products: list[str]) -> bool:
    return sorted(reactants) != sorted(products)


def mapped_species_edges(
    *,
    reaction: dict[str, Any],
    reactants: list[str],
    products: list[str],
    states_by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    """Project a reaction hyperedge onto readable species-to-species edges."""

    family = str(reaction.get("family", "unknown"))
    if family == "electron":
        return _electron_edges(reactants, products)
    if family == "ion_neutral" and len(reactants) >= 2:
        return _ion_neutral_edges(reactants, products, states_by_id)
    return [(source, product) for source in reactants for product in products]


def _electron_edges(
    reactants: list[str],
    products: list[str],
) -> list[tuple[str, str]]:
    if not reactants:
        return []
    source = reactants[-1]
    return [(source, product) for product in products if product != source]


def _ion_neutral_edges(
    reactants: list[str],
    products: list[str],
    states_by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    projectile, target = reactants[:2]
    return [
        (
            _best_source_for_product(
                projectile,
                target,
                product,
                states_by_id,
            ),
            product,
        )
        for product in products
    ]


def _best_source_for_product(
    projectile: str,
    target: str,
    product: str,
    states_by_id: dict[str, dict[str, Any]],
) -> str:
    product_composition = _composition(product, states_by_id)
    projectile_composition = _composition(projectile, states_by_id)
    target_composition = _composition(target, states_by_id)
    if (
        product_composition
        and projectile_composition == product_composition
        and product == _neutral_or_same(projectile)
    ):
        return projectile
    if product_composition and _contains(target_composition, product_composition):
        return target
    if product_composition and _contains(projectile_composition, product_composition):
        return projectile
    return target


def _neutral_or_same(species_id: str) -> str:
    return species_id[:-1] if species_id.endswith(("+", "-")) else species_id


def _composition(
    species_id: str,
    states_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    composition = states_by_id.get(species_id, {}).get("composition", {}) or {}
    return {str(element): float(count) for element, count in composition.items()}


def _contains(source: dict[str, float], product: dict[str, float]) -> bool:
    return bool(source and product) and all(
        source.get(element, 0.0) + 1e-12 >= count for element, count in product.items()
    )


__all__ = ["mapped_species_edges", "non_electron_species", "reaction_changes_species"]
