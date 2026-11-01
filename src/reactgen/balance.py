"""One conservation calculation shared by Registry checks and assessment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from reactgen.model import (
    ELECTRON,
    StateCandidate,
    Term,
    stoichiometric_product,
    stoichiometric_sum,
)
from reactgen.records import RegistryReaction, Species


@dataclass(frozen=True)
class Balance:
    missing: tuple[str, ...]
    left_charge: float
    right_charge: float
    left_elements: dict[str, float]
    right_elements: dict[str, float]
    charge_difference: float
    element_differences: dict[str, float]

    @property
    def charge_conserved(self) -> bool:
        return self.charge_difference == 0

    @property
    def elements_conserved(self) -> bool:
        return not self.element_differences


EvidenceSpecies = Species | StateCandidate


def conservation(
    reactants: list[Term] | tuple[Term, ...],
    products: list[Term] | tuple[Term, ...],
    species: Mapping[str, EvidenceSpecies],
) -> Balance:
    terms = (*reactants, *products)
    missing = tuple(sorted({term.species for term in terms if term.species not in species}))
    if missing:
        return Balance(missing, 0.0, 0.0, {}, {}, 0.0, {})
    # Difference the original contributions. Summing each side first can round
    # away a small additional term beside a large cancelling contribution.
    difference = (*products, *(Term(term.species, -term.n) for term in reactants))
    return Balance(
        (),
        _charge(reactants, species),
        _charge(products, species),
        _elements(reactants, species),
        _elements(products, species),
        _charge(difference, species),
        _elements(difference, species),
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
        return (
            f"charge {result.left_charge:+g} -> {result.right_charge:+g}; "
            f"difference {result.charge_difference:+g}"
        )

    off = result.element_differences
    if off:
        detail = ", ".join(f"{k}{v:+g}" for k, v in sorted(off.items()))
        return f"element balance: {detail}"
    return None


def _charge(
    terms: list[Term] | tuple[Term, ...],
    species: Mapping[str, EvidenceSpecies],
) -> float:
    return stoichiometric_sum(
        stoichiometric_product(term.n, species[term.species].charge) for term in terms
    )


def _elements(
    terms: list[Term] | tuple[Term, ...],
    species: Mapping[str, EvidenceSpecies],
) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for term in terms:
        if term.species == ELECTRON:
            continue
        for element, count in species[term.species].composition.items():
            totals.setdefault(element, []).append(stoichiometric_product(term.n, count))
    return {
        name: total
        for name, values in sorted(totals.items())
        if (total := stoichiometric_sum(values)) != 0
    }
