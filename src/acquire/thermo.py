"""Read formation enthalpy and standard entropy from the `chemicals` package.

`chemicals` ships its thermodynamic tables inside the distribution, so this
needs no network, no scraping and no unstable download url — the reason the
other bulk sources stayed manual. It also covers radicals such as CF3, which
compound databases do not index at all.

Two values per species are enough to screen a reaction:

    Delta G(T) = Delta H - T Delta S

which decides whether a neutral-neutral channel is open before anyone measures
a rate. The package is an optional dependency; without it this returns nothing
rather than failing.
"""

from __future__ import annotations

from dataclasses import dataclass

from acquire.pubchem import parse_formula

JOULE_PER_EV = 96485.33212  # J/mol per eV/molecule


@dataclass(frozen=True)
class Thermo:
    species: str
    cas: str | None = None
    formula: str | None = None
    enthalpy_eV: float | None = None
    entropy_J_mol_K: float | None = None
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.enthalpy_eV is not None


def available() -> bool:
    try:
        import chemicals  # noqa: F401
    except ImportError:
        return False
    return True


def fetch(names: list[str], composition: dict[str, dict[str, int]] | None = None) -> list[Thermo]:
    """One record per species, in the order given.

    ``composition`` is checked against the formula the package returns. Name
    lookup here is fuzzy — asking for the radical ``CF`` yields fluoromethane —
    and a wrong enthalpy would silently corrupt every reaction it screens, so a
    mismatch is refused rather than recorded.
    """

    if not available():
        return [Thermo(name, error="chemicals is not installed") for name in names]
    wanted = composition or {}
    return [_one(name, wanted.get(name)) for name in names]


def _one(name: str, wanted: dict[str, int] | None) -> Thermo:
    from chemicals import CAS_from_any, Hfg, S0g, search_chemical

    try:
        cas = CAS_from_any(name)
        formula = search_chemical(cas).formula
    except (ValueError, LookupError, AttributeError) as error:
        return Thermo(name, error=f"{type(error).__name__}: {str(error)[:60]}")

    if wanted and parse_formula(formula) != wanted:
        return Thermo(name, cas, formula, error=f"resolves to {formula}, a different compound")

    enthalpy = Hfg(cas)
    return Thermo(
        species=name,
        cas=cas,
        formula=formula,
        enthalpy_eV=None if enthalpy is None else enthalpy / JOULE_PER_EV,
        entropy_J_mol_K=S0g(cas),
    )


def records(found: list[Thermo], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, one per value that exists."""

    out = []
    for item in found:
        if item.enthalpy_eV is not None:
            out.append(_record(item, "enthalpy_formation_eV", item.enthalpy_eV, "eV", citation))
        if item.entropy_J_mol_K is not None:
            out.append(_record(item, "entropy_J_mol_K", item.entropy_J_mol_K, "J/mol/K", citation))
    return out


def _record(item: Thermo, name: str, value: float, unit: str, citation: str) -> dict:
    return {
        "species": item.species,
        "property": name,
        "value": value,
        "unit": unit,
        "source": {"citation": f"{citation}, CAS {item.cas}"},
    }
