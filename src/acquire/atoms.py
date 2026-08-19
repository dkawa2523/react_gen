"""Read atomic ionization energy and electron affinity from `mendeleev`.

The safest source in this repository. A chemical *name* is ambiguous — asking
for `CO` returns cobalt, asking for `CF` returns fluoromethane — but an element
symbol is not, so nothing here needs the composition check every other importer
carries.

Electron affinity is the value that decides whether an atom binds an extra
electron at all. Argon's is negative, which is why `e + Ar -> Ar-` is not a
reaction, and knowing that lets a proposer refuse to write one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Atom:
    symbol: str
    ionization_eV: float | None = None
    affinity_eV: float | None = None
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
    return Atom(
        symbol=symbol,
        ionization_eV=found.ionenergies.get(1),
        affinity_eV=found.electron_affinity,
    )


def records(found: list[Atom], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, one per value that exists."""

    out = []
    for atom in found:
        if atom.ionization_eV is not None:
            out.append(_record(atom, "ionization_energy_eV", atom.ionization_eV, citation))
        if atom.affinity_eV is not None:
            out.append(_record(atom, "electron_affinity_eV", atom.affinity_eV, citation))
    return out


def _record(atom: Atom, name: str, value: float, citation: str) -> dict:
    return {
        "species": atom.symbol,
        "property": name,
        "value": value,
        "unit": "eV",
        "source": {"citation": citation},
    }
