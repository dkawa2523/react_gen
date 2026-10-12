"""Read model enthalpy h(300 K) from PyroMat's ideal-gas records.

The h(T) method returns enthalpy in the model's energy convention, not a
standard formation enthalpy at an interchangeable reference temperature.
Keep the source model, reference declarations and conditions. No formation
quantity is derived by this adapter. PyroMat's official implementation:
https://github.com/chmarti1/PYroMat/blob/master/src/pyromat/registry/ig2.py
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from importlib.metadata import version
from typing import Any

JOULE_PER_EV = 96.48533212  # kJ/mol per eV/molecule
REFERENCE_K = 300.0


@dataclass(frozen=True)
class Enthalpy:
    """Enthalpy in eV per particle at temperature_K, not a formation value."""

    species: str
    enthalpy_eV: float | None = None
    formula: str | None = None
    error: str | None = None
    temperature_K: float = REFERENCE_K
    source_record: dict[str, Any] = field(default_factory=dict)
    package_version: str | None = None

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
    import pyromat as pm

    units = {"unit_energy": "kJ", "unit_matter": "mol", "unit_temperature": "K"}
    original = {key: pm.config[key] for key in units}
    wanted = composition or {}
    try:
        for key, value in units.items():
            pm.config[key] = value
        return [_one(name, wanted.get(name)) for name in names]
    finally:
        for key, value in original.items():
            pm.config[key] = value


def _one(name: str, wanted: dict[str, int] | None) -> Enthalpy:
    import pyromat as pm

    try:
        species = pm.get(f"ig.{name}")
    except pm.utility.PMParamError as error:
        return Enthalpy(name, error=f"{type(error).__name__}: {str(error)[:50]}")

    formula = _formula(species)
    if wanted and formula is None:
        return Enthalpy(name, error="source composition is unavailable; target match is unresolved")
    if wanted and formula != wanted:
        return Enthalpy(name, formula=_written(formula), error="composition does not match")
    declared = getattr(species, "data", {})
    if not isinstance(declared, dict):
        return Enthalpy(name, error="unsupported PyroMat source record")
    try:
        value = _scalar(species.h(T=REFERENCE_K))
    except (pm.utility.Error, ValueError, TypeError, ArithmeticError) as error:
        return Enthalpy(name, error=f"{type(error).__name__}: {str(error)[:50]}")
    return Enthalpy(
        name,
        value / JOULE_PER_EV,
        _written(formula),
        source_record=deepcopy(declared),
        package_version=version("pyromat"),
    )


def _scalar(value: Any) -> float:
    """A single finite h(T) value; never select the first of several values."""
    if hasattr(value, "item"):
        value = value.item()
    elif isinstance(value, list | tuple):
        if len(value) != 1:
            raise ValueError("h(T) returned multiple or no values")
        value = value[0]
    if isinstance(value, bool):
        raise ValueError("h(T) returned a boolean")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("h(T) returned a non-finite value")
    return number


def _formula(species: object) -> dict[str, int] | None:
    atoms = getattr(species, "atoms", None)
    if not callable(atoms):
        return None
    try:
        declared = atoms()
        if any(isinstance(value, bool) or int(value) != value for value in declared.values()):
            return None
        return {str(key): int(value) for key, value in declared.items()}
    except (TypeError, ValueError, OverflowError):
        return None


def _written(composition: dict[str, int] | None) -> str | None:
    if not composition:
        return None
    return "".join(f"{e}{n if n > 1 else ''}" for e, n in sorted(composition.items()))


def records(found: list[Enthalpy], citation: str) -> list[dict]:
    """Keep h(T) as h(T); the current formation-energy evaluator does not use it."""
    return [
        {
            "species": item.species,
            "property": "enthalpy_eV",
            "quantity": "model_enthalpy",
            "value": item.enthalpy_eV,
            "unit": "eV",
            "phase": "gas",
            "temperature_K": item.temperature_K,
            "reference_temperature_K": item.source_record.get("Tref"),
            "standard_pressure_Pa": item.source_record.get("pref"),
            "reference_declarations": {
                key: item.source_record.get(key) for key in ("Tref", "ho", "pref", "Tlim")
            },
            "qualifier": "model h(T); formation enthalpy is not determined by this acquisition",
            "status": "imported",
            "source_record": item.source_record,
            "package_version": item.package_version,
            "source": {"citation": f"{citation}, read at {REFERENCE_K:.0f} K"},
        }
        for item in found
        if item.enthalpy_eV is not None
    ]
