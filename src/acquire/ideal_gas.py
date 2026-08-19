"""Read formation enthalpy from `pyromat`'s ideal-gas tables.

PyroMat carries the NASA Glenn ideal-gas collection — 985 species, including
radicals the standard thermochemical compilations leave out. Where `chemicals`
aggregates seven curated sources and still has no `CF`, this has it.

It is also the source that caught an error elsewhere: asked for `CF`, name
lookup in a compound database returns fluoromethane at -236 kJ/mol, while the
radical is near +255. The two disagree by 492 kJ/mol, which is why every
importer here checks the formula before it trusts a number.

The enthalpy is read at 300 K, the lowest temperature these polynomials are
fitted over. That is 1.85 K above the standard state, worth a few hundredths of
an eV, and the offset is recorded in the source note rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

JOULE_PER_EV = 96.48533212  # kJ/mol per eV/molecule
REFERENCE_K = 300.0


@dataclass(frozen=True)
class Enthalpy:
    species: str
    enthalpy_eV: float | None = None
    formula: str | None = None
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.enthalpy_eV is not None


def available() -> bool:
    try:
        import pyromat  # noqa: F401
    except ImportError:
        return False
    return True


def fetch(names: list[str], composition: dict[str, dict[str, int]] | None = None) -> list[Enthalpy]:
    """One record per species, checked against the composition when given."""

    if not available():
        return [Enthalpy(name, error="pyromat is not installed") for name in names]
    _configure()
    wanted = composition or {}
    return [_one(name, wanted.get(name)) for name in names]


def _configure() -> None:
    import pyromat as pm

    pm.config["unit_energy"] = "kJ"
    pm.config["unit_matter"] = "mol"
    pm.config["unit_temperature"] = "K"


def _one(name: str, wanted: dict[str, int] | None) -> Enthalpy:
    import numpy as np
    import pyromat as pm

    try:
        species = pm.get(f"ig.{name}")
    except Exception as error:  # pyromat raises its own type for an unknown id
        return Enthalpy(name, error=f"{type(error).__name__}: {str(error)[:50]}")

    formula = _formula(species)
    if wanted and formula and formula != wanted:
        return Enthalpy(name, formula=_written(formula), error="composition does not match")
    try:
        value = float(np.atleast_1d(species.h(T=REFERENCE_K))[0])
    except Exception as error:
        return Enthalpy(name, error=f"{type(error).__name__}: {str(error)[:50]}")
    return Enthalpy(name, value / JOULE_PER_EV, _written(formula))


def _formula(species: object) -> dict[str, int] | None:
    atoms = getattr(species, "atoms", None)
    if not callable(atoms):
        return None
    try:
        return {str(k): int(v) for k, v in atoms().items()}
    except Exception:
        return None


def _written(composition: dict[str, int] | None) -> str | None:
    if not composition:
        return None
    return "".join(f"{e}{n if n > 1 else ''}" for e, n in sorted(composition.items()))


def records(found: list[Enthalpy], citation: str) -> list[dict]:
    return [
        {
            "species": item.species,
            "property": "enthalpy_formation_eV",
            "value": round(item.enthalpy_eV, 6),
            "unit": "eV",
            "source": {"citation": f"{citation}, read at {REFERENCE_K:.0f} K"},
        }
        for item in found
        if item.enthalpy_eV is not None
    ]
