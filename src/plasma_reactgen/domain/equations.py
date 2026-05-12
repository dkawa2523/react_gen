from __future__ import annotations

from plasma_reactgen.domain.models import SpeciesAmount


def format_equation(
    reactants: list[SpeciesAmount],
    products: list[SpeciesAmount],
) -> str:
    lhs = " + ".join(format_amount(x) for x in reactants)
    rhs = " + ".join(format_amount(x) for x in products)
    return f"{lhs} -> {rhs}"


def format_amount(amount: SpeciesAmount) -> str:
    if abs(amount.n - 1.0) < 1e-12:
        return amount.species
    if float(amount.n).is_integer():
        return f"{int(amount.n)} {amount.species}"
    return f"{amount.n:g} {amount.species}"
