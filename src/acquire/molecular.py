"""Read molecular dipole and Lennard-Jones parameters from ``chemicals``.

The retrieved formula must match the requested neutral ground-state species.
These properties neither establish its existence nor determine a reaction rate.
The source diameter is converted to collision radius by division by two.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from acquire.targets import chemical_identity, ground_problem
from reactgen.naming import parse_formula

# chemicals reports the Lennard-Jones collision integral diameter in angstrom,
# and the registry's collision_radius_A is half of it.
DIAMETER_TO_RADIUS = 0.5


@dataclass(frozen=True)
class Molecule:
    """One species' molecular properties, or why there are none."""

    species: str
    cas: str | None = None
    dipole_D: float | None = None
    collision_radius_A: float | None = None
    well_depth_K: float | None = None
    error: str | None = None
    identity: dict = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return any(
            value is not None
            for value in (self.dipole_D, self.collision_radius_A, self.well_depth_K)
        )


def available() -> bool:
    try:
        import chemicals  # noqa: F401
    except ImportError:
        return False
    return True


def fetch(
    species: list[str], composition: dict[str, dict[str, int]] | None = None
) -> list[Molecule]:
    if not available():
        return [Molecule(name, error="chemicals is not installed") for name in species]
    return [_one(name, (composition or {}).get(name)) for name in species]


def _one(name: str, wanted: dict[str, int] | None = None) -> Molecule:
    if problem := ground_problem(name):
        return Molecule(name, error=problem)
    from chemicals import dipole, lennard_jones
    from chemicals.identifiers import CAS_from_any, search_chemical

    try:
        cas = CAS_from_any(name)
        metadata = search_chemical(cas)
        formula = metadata.formula
    except Exception as error:  # chemicals raises bare exceptions for an unknown name
        if type(error) is not Exception and not isinstance(error, ValueError | LookupError):
            raise
        return Molecule(name, error=f"{type(error).__name__}: {str(error)[:50]}")
    target = wanted or parse_formula(name)
    if target and parse_formula(formula) != target:
        return Molecule(name, cas=cas, error=f"resolves to {formula}, a different compound")

    diameter = _lookup(lennard_jones.molecular_diameter, cas)
    return Molecule(
        species=name,
        cas=cas,
        dipole_D=_lookup(dipole.dipole_moment, cas),
        collision_radius_A=None if diameter is None else round(diameter * DIAMETER_TO_RADIUS, 4),
        well_depth_K=_lookup(lennard_jones.Stockmayer, cas),
        identity=chemical_identity(metadata, cas),
    )


def _lookup(reader, cas: str) -> float | None:
    """An absent upstream value is None; dependency and implementation errors propagate."""
    value = reader(CASRN=cas)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("molecular source property must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("molecular source property must be a finite number")
    return number


def records(found: list[Molecule], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, one per value that exists."""

    fields = (
        ("dipole_D", "dipole_moment_D", "D"),
        ("collision_radius_A", "collision_radius_A", "A"),
        ("well_depth_K", "well_depth_K", "K"),
    )
    out = []
    for item in found:
        for attribute, name, unit in fields:
            value = getattr(item, attribute)
            if value is not None:
                out.append(_record(item, name, value, unit, citation))
    return out


def _record(item: Molecule, name: str, value: float, unit: str, citation: str) -> dict:
    return {
        "species": item.species,
        "property": name,
        "value": value,
        "unit": unit,
        "phase": "gas",
        "source_identity": item.identity,
        "source": {"citation": f"{citation}, CAS {item.cas}"},
    }
