"""Conservation checks applied to every reaction before it enters a network."""

from __future__ import annotations

from collections import defaultdict

from reactgen.model import ELECTRON, Reaction, Species, Term

TOLERANCE = 1e-9


def imbalance(reaction: Reaction, species: dict[str, Species]) -> str | None:
    """Return why the reaction is rejected, or None when it is sound.

    Surface channels are exempt from charge balance: the wall absorbs the
    charge, and the returned neutral is the only gas-phase product.
    """

    unknown = sorted(
        term.species
        for term in (*reaction.reactants, *reaction.products)
        if term.species not in species
    )
    if unknown:
        return f"unregistered species: {', '.join(unknown)}"

    if reaction.surface is None:
        left, right = _charge(reaction.reactants, species), _charge(reaction.products, species)
        if abs(left - right) > TOLERANCE:
            return f"charge {left:+g} -> {right:+g}"

    delta = _elements(reaction.products, species)
    for element, count in _elements(reaction.reactants, species).items():
        delta[element] -= count
    off = {k: v for k, v in delta.items() if abs(v) > TOLERANCE}
    if off:
        detail = ", ".join(f"{k}{v:+g}" for k, v in sorted(off.items()))
        return f"element balance: {detail}"
    return None


def _charge(terms: list[Term], species: dict[str, Species]) -> float:
    return sum(term.n * species[term.species].charge for term in terms)


def _elements(terms: list[Term], species: dict[str, Species]) -> defaultdict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for term in terms:
        if term.species == ELECTRON:
            continue
        for element, count in species[term.species].composition.items():
            totals[element] += term.n * count
    return totals
