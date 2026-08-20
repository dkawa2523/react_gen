"""Read atomic ionization energy and electron affinity from `mendeleev`.

The safest source in this repository. A chemical *name* is ambiguous — asking
for `CO` returns cobalt, asking for `CF` returns fluoromethane — but an element
symbol is not, so nothing here needs the composition check every other importer
carries.

Electron affinity is the value that decides whether an atom binds an extra
electron at all. Argon's is negative, which is why `e + Ar -> Ar-` is not a
reaction, and knowing that lets a proposer refuse to write one.

Dipole polarizability comes from the same table, and it is the only place in
this repository where polarizability can be read rather than typed in by hand:
neither `chemicals` nor `thermo` tabulates it, and the Lorentz-Lorenz route
through refractive index answers for three species out of fifty-seven. For an
atom the table is right -- argon lands at 1.642 A3 against a measured 1.641 --
so every atomic species can be filled, and molecules stay a manual export.
"""

from __future__ import annotations

from dataclasses import dataclass

# mendeleev reports dipole polarizability in atomic units.
CUBIC_ANGSTROM_PER_AU = 0.1481847113


@dataclass(frozen=True)
class Atom:
    symbol: str
    ionization_eV: float | None = None
    affinity_eV: float | None = None
    polarizability_A3: float | None = None
    error: str | None = None

    @property
    def binds_electron(self) -> bool | None:
        """Whether an extra electron is bound. None when unknown."""
        return None if self.affinity_eV is None else self.affinity_eV > 0


def available() -> bool:
    try:
        import mendeleev  # noqa: F401
    except ImportError:
        return False
    return True


def fetch(symbols: list[str]) -> list[Atom]:
    if not available():
        return [Atom(s, error="mendeleev is not installed") for s in symbols]
    return [_one(symbol) for symbol in symbols]


def _one(symbol: str) -> Atom:
    from mendeleev import element

    try:
        found = element(symbol)
    except Exception as error:  # mendeleev raises bare exceptions for an unknown symbol
        return Atom(symbol, error=f"{type(error).__name__}: {str(error)[:50]}")
    polarizability = getattr(found, "dipole_polarizability", None)
    return Atom(
        symbol=symbol,
        ionization_eV=found.ionenergies.get(1),
        affinity_eV=found.electron_affinity,
        polarizability_A3=(
            None if polarizability is None else round(polarizability * CUBIC_ANGSTROM_PER_AU, 4)
        ),
    )


def records(found: list[Atom], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, one per value that exists."""

    out = []
    for atom in found:
        if atom.ionization_eV is not None:
            out.append(_record(atom, "ionization_energy_eV", atom.ionization_eV, "eV", citation))
        if atom.affinity_eV is not None:
            out.append(_record(atom, "electron_affinity_eV", atom.affinity_eV, "eV", citation))
        if atom.polarizability_A3 is not None:
            out.append(
                _record(
                    atom,
                    "polarizability_A3",
                    atom.polarizability_A3,
                    "A3",
                    f"{citation}, dipole polarizability in atomic units",
                )
            )
    return out


def _record(atom: Atom, name: str, value: float, unit: str, citation: str) -> dict:
    return {
        "species": atom.symbol,
        "property": name,
        "value": value,
        "unit": unit,
        "source": {"citation": citation},
    }
