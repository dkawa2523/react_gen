from __future__ import annotations

from collections import defaultdict

from plasma_reactgen.domain.models import Species, SpeciesAmount


def validate_reaction(
    reactants: list[SpeciesAmount],
    products: list[SpeciesAmount],
    species: dict[str, Species],
) -> dict[str, str]:
    return {
        "species_reference": check_species_reference(reactants, products, species),
        "charge_balance": check_charge_balance(reactants, products, species),
        "element_balance": check_element_balance(reactants, products, species),
    }


def check_species_reference(
    reactants: list[SpeciesAmount],
    products: list[SpeciesAmount],
    species: dict[str, Species],
) -> str:
    for amount in [*reactants, *products]:
        if amount.species == "e":
            continue
        if amount.species not in species:
            return "unknown_species"
    return "ok"


def check_charge_balance(
    reactants: list[SpeciesAmount],
    products: list[SpeciesAmount],
    species: dict[str, Species],
) -> str:
    if check_species_reference(reactants, products, species) != "ok":
        return "unknown_species"

    lhs = sum(amount.n * get_charge(amount.species, species) for amount in reactants)
    rhs = sum(amount.n * get_charge(amount.species, species) for amount in products)
    return "ok" if abs(lhs - rhs) < 1e-12 else "failed"


def check_element_balance(
    reactants: list[SpeciesAmount],
    products: list[SpeciesAmount],
    species: dict[str, Species],
) -> str:
    if check_species_reference(reactants, products, species) != "ok":
        return "unknown_species"

    lhs: dict[str, float] = defaultdict(float)
    rhs: dict[str, float] = defaultdict(float)

    for amount in reactants:
        if amount.species == "e":
            continue
        for elem, count in species[amount.species].composition.items():
            lhs[elem] += amount.n * count

    for amount in products:
        if amount.species == "e":
            continue
        for elem, count in species[amount.species].composition.items():
            rhs[elem] += amount.n * count

    for elem in set(lhs) | set(rhs):
        if abs(lhs[elem] - rhs[elem]) > 1e-12:
            return "failed"
    return "ok"


def get_charge(species_id: str, species: dict[str, Species]) -> int:
    if species_id == "e":
        return -1
    return species[species_id].charge
