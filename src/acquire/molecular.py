"""Read molecular dipole and Lennard-Jones parameters from ``chemicals``.

The retrieved formula must match the requested neutral ground-state species.
These properties neither establish its existence nor determine a reaction rate.
The source diameter is converted to collision radius by division by two.
"""

from __future__ import annotations

from dataclasses import dataclass

from acquire.pubchem import parse_formula
from reactgen.chemistry import parse_state_id

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
    from chemicals import dipole, lennard_jones
    from chemicals.identifiers import CAS_from_any, search_chemical

    try:
        cas = CAS_from_any(name)
        formula = search_chemical(cas).formula
    except Exception as error:  # chemicals raises bare exceptions for an unknown name
        return Molecule(name, error=f"{type(error).__name__}: {str(error)[:50]}")
    target = wanted or parse_formula(name)
    state = parse_state_id(name)
    if state is not None and (state.charge or state.state.kind != "ground" or state.phase != "gas"):
        return Molecule(name, cas=cas, error="this source provides neutral ground-state properties")
    if target and parse_formula(formula) != target:
        return Molecule(name, cas=cas, error=f"resolves to {formula}, a different compound")

    diameter = _quietly(lennard_jones.molecular_diameter, cas)
    return Molecule(
        species=name,
        cas=cas,
        dipole_D=_quietly(dipole.dipole_moment, cas),
        collision_radius_A=None if diameter is None else round(diameter * DIAMETER_TO_RADIUS, 4),
        well_depth_K=_quietly(lennard_jones.Stockmayer, cas),
    )


def _quietly(reader, cas: str) -> float | None:
    """A lookup that answers None rather than raising when a compound is absent."""

    try:
        value = reader(CASRN=cas)
    except Exception:
        return None
    return None if value is None else float(value)


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
        "composition": parse_formula(item.species),
        "source": {"citation": f"{citation}, CAS {item.cas}"},
    }
