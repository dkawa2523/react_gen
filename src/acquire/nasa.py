"""Read gas-phase NASA fits from Cantera's explicit ``nasa_gas.yaml`` source.

Composition and charge narrow the match; competing structural identities are
not selected by file order. This adapter does not establish state existence or
derive excited-state thermodynamic populations. Cantera's thermo reference
pressure is 1 atm unless the source specifies otherwise:
https://cantera.org/stable/yaml/species.html#species-thermo-models
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from reactgen import yamlio

# The element cantera uses for the electron in an ionised mechanism.
ELECTRON_ELEMENT = "E"


@dataclass(frozen=True)
class Polynomial:
    """One species' thermodynamic fit, or why there is none."""

    species: str
    model: str | None = None
    temperature_ranges: list[float] = field(default_factory=list)
    coefficients: list[list[float]] = field(default_factory=list)
    listed_as: str | None = None
    origin: str | None = None
    error: str | None = None
    phase: str = "gas"
    standard_pressure_Pa: float | None = None
    structure: str | None = None

    @property
    def known(self) -> bool:
        return self.nasa7 != (None, None)

    @property
    def nasa7(self) -> tuple[tuple[float, ...] | None, tuple[float, ...] | None]:
        """The low and high seven-term rows, or a pair of None for anything else."""

        rows = [tuple(row) for row in self.coefficients]
        if (
            self.model != "NASA7"
            or len(rows) not in {1, 2}
            or any(len(row) != 7 for row in rows)
            or len(self.temperature_ranges) != len(rows) + 1
        ):
            return None, None
        if any(not math.isfinite(value) for row in rows for value in row) or any(
            not math.isfinite(value) or value <= 0 for value in self.temperature_ranges
        ):
            return None, None
        if any(
            left >= right
            for left, right in zip(
                self.temperature_ranges, self.temperature_ranges[1:], strict=False
            )
        ):
            return None, None
        return (rows[0], rows[-1])

    @property
    def unusable(self) -> str | None:
        """Why a matched species still yields nothing, for the run to report."""

        if self.error or self.known:
            return None
        return f"{self.model or 'no'} fit, which the registry's NASA7 field cannot hold"


def available() -> bool:
    try:
        import cantera  # noqa: F401
    except ImportError:
        return False
    return True


def catalog() -> dict[tuple[tuple[tuple[str, int], ...], int], list[dict[str, Any]]]:
    """Keep all identities in the gas compilation; condensed fits never enter."""

    import cantera as ct

    root = os.path.join(os.path.dirname(ct.__file__), "data")
    found: dict[tuple[tuple[tuple[str, int], ...], int], list[dict[str, Any]]] = {}
    path = os.path.join(root, "nasa_gas.yaml")
    document = _document(path)
    for entry in (document or {}).get("species") or []:
        if not entry.get("thermo"):
            continue
        key = _key(entry.get("composition") or {})
        if key is not None:
            found.setdefault(key, []).append({**entry, "origin": "nasa_gas.yaml"})
    return found


def _document(path: str) -> dict | None:
    """One bundled file, or None where this cantera build cannot parse it."""

    try:
        with open(path, encoding="utf-8") as handle:
            return yamlio.load(handle)
    except (OSError, yaml.YAMLError):
        return None


def _key(composition: dict) -> tuple[tuple[tuple[str, int], ...], int] | None:
    try:
        if any(isinstance(v, bool) or float(v) != int(v) for v in composition.values()):
            return None
        counts = {str(k): int(v) for k, v in composition.items()}
    except (TypeError, ValueError):  # a fractional composition is not a species here
        return None
    charge = -counts.pop(ELECTRON_ELEMENT, 0)
    return tuple(sorted(counts.items())), charge


def fetch(species: list[dict]) -> list[Polynomial]:
    """One polynomial per requested species; each dict needs id, composition, charge."""

    if not available():
        return [Polynomial(str(s.get("id")), error="cantera is not installed") for s in species]
    listed = catalog()
    return [_one(item, listed) for item in species]


def _one(item: dict, listed: dict) -> Polynomial:
    name = str(item.get("id"))
    if item.get("phase", "gas") != "gas":
        return Polynomial(name, error="this adapter supplies gas-phase fits only")
    kind = str((item.get("state") or {}).get("kind", "ground"))
    if kind not in ("ground", "ion"):
        return Polynomial(
            name, error=f"{kind} state; its thermodynamic populations need independent evidence"
        )
    composition = {str(k): int(v) for k, v in (item.get("composition") or {}).items()}
    key = (tuple(sorted(composition.items())), int(item.get("charge", 0)))
    entries = listed.get(key, [])
    if not entries:
        return Polynomial(name, error="no bundled fit for this composition and charge")
    structure = item.get("structure")
    source_species = item.get("source_species") or structure
    if source_species:
        entries = [entry for entry in entries if entry.get("name") == source_species]
    if len(entries) != 1:
        return Polynomial(
            name, error="ambiguous structural identity; specify source_species", structure=structure
        )
    entry = entries[0]
    thermo = entry["thermo"]
    return Polynomial(
        species=name,
        model=str(thermo.get("model")),
        temperature_ranges=[float(t) for t in thermo.get("temperature-ranges") or []],
        coefficients=[[float(c) for c in row] for row in thermo.get("data") or []],
        listed_as=str(entry.get("name")),
        origin=str(entry.get("origin")),
        standard_pressure_Pa=_reference_pressure(thermo.get("reference-pressure", "1 atm")),
        structure=str(source_species) if source_species else None,
    )


def records(found: list[Polynomial], citation: str) -> list[dict]:
    """Thermo records for `rgen ingest`, one per species with a usable fit.

    The registry holds a NASA 7-coefficient polynomial with a low and a high
    range, so that is what is emitted. A bundled fit with one range fills both
    from it, which is what a single-range fit means. NASA9 is left alone rather
    than truncated to seven terms -- the two forms are different functions, and
    silently dropping the T^-2 and T^-1 terms would move Cp near 300 K.
    """

    out = []
    for item in found:
        low, high = item.nasa7
        if low is None or high is None:
            continue
        boundaries = item.temperature_ranges
        out.append(
            {
                "species": item.species,
                "thermo": {
                    "low": list(low),
                    "high": list(high),
                    "t_min": boundaries[0],
                    "t_mid": boundaries[1] if len(boundaries) > 2 else boundaries[-1],
                    "t_max": boundaries[-1],
                    "source": f"{citation}, listed as {item.listed_as} in {item.origin}",
                    "phase": item.phase,
                    "standard_pressure_Pa": item.standard_pressure_Pa,
                },
                "phase": item.phase,
                "structure": item.structure,
                "source_species": item.listed_as,
            }
        )
    return out


def _reference_pressure(value: object) -> float | None:
    """Cantera declares a pressure in Pa numerically or with an explicit unit."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) and value > 0 else None
    written = str(value).split()
    if len(written) != 2:
        return None
    factor = {"Pa": 1.0, "kPa": 1000.0, "bar": 100000.0, "atm": 101325.0}.get(written[1])
    try:
        number = float(written[0])
    except ValueError:
        return None
    return number * factor if factor and math.isfinite(number) and number > 0 else None
