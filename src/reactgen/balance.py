"""One conservation calculation shared by Registry checks and assessment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from reactgen.model import ELECTRON, StateCandidate, Term
from reactgen.records import RegistryReaction, Species

TOLERANCE = 1e-9


@dataclass(frozen=True)
class Balance:
    missing: tuple[str, ...]
    left_charge: float
    right_charge: float
    left_elements: dict[str, float]
    right_elements: dict[str, float]

    @property
    def charge_conserved(self) -> bool:
        return abs(self.left_charge - self.right_charge) <= TOLERANCE

    @property
    def elements_conserved(self) -> bool:
        elements = set(self.left_elements) | set(self.right_elements)
        return all(
            abs(self.left_elements.get(name, 0.0) - self.right_elements.get(name, 0.0)) <= TOLERANCE
            for name in elements
        )


EvidenceSpecies = Species | StateCandidate


def conservation(
    reactants: list[Term] | tuple[Term, ...],
    products: list[Term] | tuple[Term, ...],
    species: Mapping[str, EvidenceSpecies],
) -> Balance:
    terms = (*reactants, *products)
    missing = tuple(sorted({term.species for term in terms if term.species not in species}))
    if missing:
        return Balance(missing, 0.0, 0.0, {}, {})
    return Balance(
        (),
        _charge(reactants, species),
        _charge(products, species),
        _elements(reactants, species),
        _elements(products, species),
    )


def imbalance(
    reaction: RegistryReaction,
    species: Mapping[str, EvidenceSpecies],
) -> str | None:
    """Return a structural inconsistency, or None when the record is sound.

    Surface channels are exempt from charge balance: the wall absorbs the
    charge, and the returned neutral is the only gas-phase product.
    """

    result = conservation(reaction.reactants, reaction.products, species)
    if result.missing:
        return f"unregistered species: {', '.join(result.missing)}"

    if reaction.surface is None and not result.charge_conserved:
        return f"charge {result.left_charge:+g} -> {result.right_charge:+g}"

    elements = set(result.left_elements) | set(result.right_elements)
    off = {
        name: result.right_elements.get(name, 0.0) - result.left_elements.get(name, 0.0)
        for name in elements
        if abs(result.right_elements.get(name, 0.0) - result.left_elements.get(name, 0.0))
        > TOLERANCE
    }
    if off:
        detail = ", ".join(f"{k}{v:+g}" for k, v in sorted(off.items()))
        return f"element balance: {detail}"
    return None


def _charge(
    terms: list[Term] | tuple[Term, ...],
    species: Mapping[str, EvidenceSpecies],
) -> float:
    return sum(term.n * species[term.species].charge for term in terms)


def _elements(
    terms: list[Term] | tuple[Term, ...],
    species: Mapping[str, EvidenceSpecies],
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for term in terms:
        if term.species == ELECTRON:
            continue
        for element, count in species[term.species].composition.items():
            totals[element] = totals.get(element, 0.0) + term.n * count
    return {name: value for name, value in sorted(totals.items()) if abs(value) > TOLERANCE}
