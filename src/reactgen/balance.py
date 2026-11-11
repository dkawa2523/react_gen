"""One conservation calculation shared by Registry checks and assessment."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

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
    isotope_conflicts: tuple[str, ...] = ()
    isotope_unresolved: tuple[str, ...] = ()

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
    element_differences = _elements(difference, species)
    isotope_conflicts, isotope_unresolved = (
        _isotope_balance(difference, species) if not element_differences else ((), ())
    )
    return Balance(
        (),
        _charge(reactants, species),
        _charge(products, species),
        _elements(reactants, species),
        _elements(products, species),
        _charge(difference, species),
        element_differences,
        isotope_conflicts,
        isotope_unresolved,
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
    if reaction.surface is None and result.isotope_conflicts:
        return "isotope balance: " + ", ".join(result.isotope_conflicts)
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


# OpenSMILES §3.1.4 gives isotope mass number before the bracket atom symbol.
# Read only this declaration, not bonds, valence, isotope abundance or atom maps.
_SMILES_ISOTOPE = re.compile(r"\[([0-9]+)([A-Z][a-z]?|as|se|[bcnops])(?=[@H+\-:\]])")


def _isotope_declaration(state: EvidenceSpecies) -> tuple[Counter[tuple[str, str]], bool]:
    structure = state.structure or ""
    if structure.startswith(("smiles:", "SMILES=")):
        # A name or CXSMILES annotation after the SMILES is not an atom token.
        notation = structure[7:].split(maxsplit=1)
        labels = Counter(
            (element.capitalize(), mass.lstrip("0") or "0")
            for mass, element in _SMILES_ISOTOPE.findall(notation[0] if notation else "")
        )
        labelled_elements: Counter[str] = Counter()
        for (element, _), count in labels.items():
            labelled_elements[element] += count
        if any(count > state.composition.get(e, 0) for e, count in labelled_elements.items()):
            return Counter(), True
        return labels, False
    # An InChI isotope layer is indexed by atom and mass shift. Keep its
    # declared identity unresolved here rather than interpreting it as SMILES.
    return Counter(), structure.startswith("InChI=") and "/i" in structure


def declares_nuclides(state: EvidenceSpecies) -> bool:
    """Check whether the structure carries resolved or opaque isotope information."""
    labels, unresolved = _isotope_declaration(state)
    return bool(labels) or unresolved


def nuclide_correspondence(initial: StateCandidate, final: StateCandidate) -> bool | None:
    """Check isotope declarations across one element-matched particle pair."""
    if not (declares_nuclides(initial) or declares_nuclides(final)):
        return True
    pair = conservation((Term(initial.id),), (Term(final.id),), {s.id: s for s in (initial, final)})
    if pair.isotope_conflicts:
        return False
    return None if pair.isotope_unresolved else True


def retained_nuclide_correspondence(
    *roles: tuple[StateCandidate, StateCandidate, Mapping[str, int]],
) -> bool | None:
    """Check the isotope inventory of each retained elemental core.

    The caller checks the exchanged groups and total conservation. Explicit
    equal labels can be retained, and unspecified nuclei can fill unmatched
    positions without establishing the exact nuclear correspondence.
    """
    declarations = {
        state.id: _isotope_declaration(state)
        for initial, final, _ in roles
        for state in (initial, final)
    }
    elements = {element for labels, _ in declarations.values() for element, _ in labels}
    unresolved = any(opaque for _, opaque in declarations.values())
    for initial, final, retained in roles:
        initial_labels, final_labels = declarations[initial.id][0], declarations[final.id][0]
        shared = initial_labels & final_labels
        for element in elements & retained.keys():
            initial_unspecified = initial.composition[element] - sum(
                count for (name, _), count in initial_labels.items() if name == element
            )
            final_unspecified = final.composition[element] - sum(
                count for (name, _), count in final_labels.items() if name == element
            )
            matched = sum(count for (name, _), count in shared.items() if name == element)
            if matched + initial_unspecified + final_unspecified < retained[element]:
                return False
            unresolved |= matched < retained[element]
    return None if unresolved else True


def _isotope_balance(
    difference: tuple[Term, ...], species: Mapping[str, EvidenceSpecies]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    declarations = {
        key: _isotope_declaration(species[key])
        for key in {term.species for term in difference if term.species != ELECTRON}
        if species[key].structure
    }
    if not any(labels or opaque for labels, opaque in declarations.values()):
        return (), ()

    left_counts, right_counts, shared_counts = _isotope_coefficients(difference)
    left, left_unlabelled, left_opaque = _isotope_inventory(left_counts, species, declarations)
    right, right_unlabelled, right_opaque = _isotope_inventory(right_counts, species, declarations)
    _, shared_unlabelled, _ = _isotope_inventory(shared_counts, species, declarations)

    # Each explicit deficit needs at least one unresolved nucleus of the
    # same element on its opposite side. One nucleus cannot fill two deficits.
    need_left: dict[str, Fraction] = defaultdict(Fraction)
    need_right: dict[str, Fraction] = defaultdict(Fraction)
    labels = left.keys() | right.keys()
    for label in labels:
        delta = right[label] - left[label]
        (need_left if delta > 0 else need_right)[label[0]] += abs(delta)
    opaque_elements = left_opaque | right_opaque
    conflicts = []
    unresolved = []
    for element in sorted(opaque_elements | {element for element, _ in labels}):
        # An unresolved species on both sides can represent different isotope
        # assignments. A coarse equation cannot decide that hidden exchange.
        gap = max(
            need_left[element] - left_unlabelled[element],
            need_right[element] - right_unlabelled[element],
        )
        if gap > shared_unlabelled[element]:
            conflicts.append(element)
        elif (
            gap > 0
            or element in opaque_elements
            or left_unlabelled[element]
            or right_unlabelled[element]
        ):
            unresolved.append(element)
    return tuple(conflicts), tuple(unresolved)


def _isotope_coefficients(
    difference: tuple[Term, ...],
) -> tuple[dict[str, Fraction], dict[str, Fraction], dict[str, Fraction]]:
    # Exact decimal coefficients separate unchanged participants, including
    # labelled spectators, before deciding which isotope labels are relevant.
    left: dict[str, Fraction] = defaultdict(Fraction)
    right: dict[str, Fraction] = defaultdict(Fraction)
    for term in difference:
        side = left if term.n < 0 else right
        side[term.species] += Fraction(str(abs(term.n)))
    shared = {key: min(left[key], right[key]) for key in left.keys() & right.keys()}
    return (
        {key: n - shared.get(key, 0) for key, n in left.items() if n > shared.get(key, 0)},
        {key: n - shared.get(key, 0) for key, n in right.items() if n > shared.get(key, 0)},
        shared,
    )


def _isotope_inventory(
    coefficients: dict[str, Fraction],
    species: Mapping[str, EvidenceSpecies],
    declarations: dict[str, tuple[Counter[tuple[str, str]], bool]],
) -> tuple[dict[tuple[str, str], Fraction], dict[str, Fraction], set[str]]:
    labelled: dict[tuple[str, str], Fraction] = defaultdict(Fraction)
    unlabelled: dict[str, Fraction] = defaultdict(Fraction)
    opaque_elements: set[str] = set()
    for state_id, coefficient in coefficients.items():
        composition = species[state_id].composition
        labels, opaque = declarations.get(state_id, (Counter(), False))
        if opaque:
            opaque_elements.update(composition)
        for element, count in composition.items():
            unlabelled[element] += coefficient * count
        for label, count in labels.items():
            labelled[label] += coefficient * count
            unlabelled[label[0]] -= coefficient * count
    return labelled, unlabelled, opaque_elements
