"""Molecular properties `chemicals` can answer for, in one pass.

`acquire thermo` already reads formation enthalpy and entropy from the same
package. This reads the rest of what it holds about a molecule as a molecule,
rather than as a thermodynamic state:

    dipole_moment_D      CCCBDB / Poling / PSI4 compilations
    collision_radius_A   half the Lennard-Jones sigma
    well_depth_K         the Stockmayer epsilon/k that comes with it

The dipole is the one that changes an answer. Forty-two of the registry's
values are zeros asserted from molecular symmetry and only four are
measurements, so a polar molecule -- SOF2, SO2, SOF4 -- currently carries no
number at all rather than a wrong one. With a real value the ion-dipole
capture rate becomes available, which Langevin alone underestimates.

Polarizability is deliberately absent. `chemicals` tabulates none, and its
`polarizability_from_RI` needs a refractive index the package has for three of
the fifty-seven neutral ground states here. Atoms are filled from `mendeleev`
by `acquire atoms`; molecules stay a manual CCCBDB export, and saying so is
better than deriving a number from a correlation fitted to organic liquids.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def fetch(species: list[str]) -> list[Molecule]:
    if not available():
        return [Molecule(name, error="chemicals is not installed") for name in species]
    return [_one(name) for name in species]


def _one(name: str) -> Molecule:
    from chemicals import dipole, lennard_jones
    from chemicals.identifiers import CAS_from_any

    try:
        cas = CAS_from_any(name)
    except Exception as error:  # chemicals raises bare exceptions for an unknown name
        return Molecule(name, error=f"{type(error).__name__}: {str(error)[:50]}")

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
        "source": {"citation": f"{citation}, CAS {item.cas}"},
    }
